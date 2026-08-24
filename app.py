import os
import uuid
import zipfile
import shutil
import gc
import warnings

from flask import (
    Flask,
    render_template,
    request,
    send_from_directory,
    abort
)

from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.utils import secure_filename


# ============================================================
# FLASK APP
# ============================================================

app = Flask(__name__)


# ============================================================
# FOLDERS
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
PROCESSED_FOLDER = os.path.join(BASE_DIR, "processed")

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["PROCESSED_FOLDER"] = PROCESSED_FOLDER


# ============================================================
# UPLOAD / MEMORY LIMITS
# ============================================================

# Maximum uploaded file size: 10 MB
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024


# IMPORTANT:
# Maximum source image pixels that we will decode.
#
# 20 million pixels is a safe limit for a small Render instance.
#
# Example:
# 5000 x 4000 = 20,000,000 pixels
#
MAX_SOURCE_PIXELS = 20_000_000


# Maximum output pixels.
#
# Example:
# 5000 x 4000 = 20,000,000 pixels
#
MAX_OUTPUT_PIXELS = 20_000_000


# Maximum width / height individually.
MAX_DIMENSION = 5000


# Maximum number of images per request.
MAX_FILES_PER_REQUEST = 10


# ============================================================
# CREATE FOLDERS
# ============================================================

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)


# ============================================================
# ALLOWED FORMATS
# ============================================================

ALLOWED_FORMATS = {
    "JPEG": "jpg",
    "PNG": "png",
    "WEBP": "webp"
}

ALLOWED_EXTENSIONS = {
    "jpg",
    "jpeg",
    "png",
    "webp"
}


# ============================================================
# PIL SAFETY
# ============================================================

# We do NOT disable Pillow's decompression bomb protection.
#
# Instead, we check image dimensions ourselves before calling
# image.load().

Image.MAX_IMAGE_PIXELS = MAX_SOURCE_PIXELS

warnings.simplefilter(
    "error",
    Image.DecompressionBombWarning
)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def safe_remove(path):
    """
    Safely delete a file or folder.
    """
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)

        elif os.path.isfile(path):
            os.remove(path)

    except Exception:
        pass


def cleanup_memory():
    """
    Force Python garbage collection.
    """
    gc.collect()


def validate_dimensions(width, height):
    """
    Validate requested output dimensions.
    """

    if width <= 0 or height <= 0:
        return False, "Width and height must be greater than 0."

    if width > MAX_DIMENSION:
        return False, (
            f"Maximum width allowed is {MAX_DIMENSION}px."
        )

    if height > MAX_DIMENSION:
        return False, (
            f"Maximum height allowed is {MAX_DIMENSION}px."
        )

    output_pixels = width * height

    if output_pixels > MAX_OUTPUT_PIXELS:
        return False, (
            f"Requested output is too large. "
            f"Maximum supported output is "
            f"{MAX_OUTPUT_PIXELS:,} pixels."
        )

    return True, ""


def validate_uploaded_image(image_path):
    """
    Open image only for metadata first.

    We check dimensions BEFORE loading/decompressing the
    complete image into RAM.
    """

    image = None

    try:
        image = Image.open(image_path)

        source_width, source_height = image.size

        source_pixels = source_width * source_height

        print(
            f"IMAGE SIZE: "
            f"{source_width} x {source_height}"
        )

        print(
            f"IMAGE PIXELS: "
            f"{source_pixels}"
        )

        print(
            f"MAX SOURCE PIXELS: "
            f"{MAX_SOURCE_PIXELS}"
        )

        if source_pixels > MAX_SOURCE_PIXELS:
            return (
                False,
                (
                    f"This image is too large to process safely. "
                    f"Maximum supported image size is "
                    f"{MAX_SOURCE_PIXELS:,} pixels. "
                    f"Your image contains "
                    f"{source_pixels:,} pixels."
                ),
                None
            )

        return (
            True,
            "",
            (source_width, source_height)
        )

    except Image.DecompressionBombError:
        return (
            False,
            (
                "This image is too large to process safely."
            ),
            None
        )

    except Image.DecompressionBombWarning:
        return (
            False,
            (
                "This image is too large to process safely."
            ),
            None
        )

    except UnidentifiedImageError:
        return (
            False,
            (
                "The uploaded file is not a valid image."
            ),
            None
        )

    except Exception as error:
        return (
            False,
            f"Unable to read image: {error}",
            None
        )

    finally:
        if image is not None:
            try:
                image.close()
            except Exception:
                pass

        cleanup_memory()


def convert_for_output(image, output_format):
    """
    Convert image to a safe mode for output format.
    """

    if output_format == "JPEG":

        if image.mode == "RGB":
            return image

        if image.mode == "RGBA":
            background = Image.new(
                "RGB",
                image.size,
                "white"
            )

            background.paste(
                image,
                mask=image.getchannel("A")
            )

            return background

        return image.convert("RGB")


    if output_format == "PNG":

        if image.mode in ("RGB", "RGBA"):
            return image

        return image.convert("RGBA")


    if output_format == "WEBP":

        if image.mode in ("RGB", "RGBA"):
            return image

        return image.convert("RGB")


    return image


def process_single_image(
    source_path,
    output_path,
    width,
    height,
    quality,
    output_format
):
    """
    Memory-conscious image processing.

    IMPORTANT:
    - Source image is opened from disk.
    - Source dimensions are validated before load.
    - Image is converted only when necessary.
    - Temporary objects are deleted.
    - Garbage collection is forced.
    """

    source_image = None
    resized_image = None
    output_image = None

    try:

        # ----------------------------------------------------
        # Open image
        # ----------------------------------------------------

        source_image = Image.open(source_path)

        source_width, source_height = source_image.size

        source_pixels = source_width * source_height

        print(
            f"IMAGE OPENED: "
            f"{os.path.basename(source_path)}"
        )

        print(
            f"IMAGE SIZE: "
            f"{source_width} x {source_height}"
        )

        print(
            f"IMAGE PIXELS: "
            f"{source_pixels}"
        )

        # ----------------------------------------------------
        # Safety check
        # ----------------------------------------------------

        if source_pixels > MAX_SOURCE_PIXELS:

            raise ValueError(
                f"This image is too large to process safely. "
                f"Maximum supported image size is "
                f"{MAX_SOURCE_PIXELS:,} pixels. "
                f"Your image contains "
                f"{source_pixels:,} pixels."
            )

        # ----------------------------------------------------
        # Load actual pixels only after validation
        # ----------------------------------------------------

        source_image.load()

        # ----------------------------------------------------
        # Correct EXIF orientation
        # ----------------------------------------------------

        try:
            source_image = ImageOps.exif_transpose(
                source_image
            )
        except Exception:
            pass

        # ----------------------------------------------------
        # Convert source image
        # ----------------------------------------------------

        if source_image.mode in (
            "RGBA",
            "LA",
            "P"
        ):
            source_image = source_image.convert("RGBA")

        else:
            source_image = source_image.convert("RGB")

        # ----------------------------------------------------
        # Resize
        # ----------------------------------------------------

        resized_image = source_image.resize(
            (width, height),
            Image.Resampling.LANCZOS
        )

        # ----------------------------------------------------
        # Output conversion
        # ----------------------------------------------------

        output_image = convert_for_output(
            resized_image,
            output_format
        )

        # ----------------------------------------------------
        # Save
        # ----------------------------------------------------

        if output_format == "JPEG":

            output_image.save(
                output_path,
                "JPEG",
                quality=quality,
                optimize=True,
                progressive=True
            )

        elif output_format == "PNG":

            output_image.save(
                output_path,
                "PNG",
                optimize=True
            )

        elif output_format == "WEBP":

            output_image.save(
                output_path,
                "WEBP",
                quality=quality,
                method=4
            )

        else:

            raise ValueError(
                "Unsupported output format."
            )

        # ----------------------------------------------------
        # Verify file
        # ----------------------------------------------------

        if not os.path.exists(output_path):

            raise RuntimeError(
                "Processed image was not created."
            )

        processed_size = os.path.getsize(
            output_path
        )

        if processed_size <= 0:

            raise RuntimeError(
                "Processed image is empty."
            )

        print(
            f"PROCESSED FILE: "
            f"{output_path}"
        )

        print(
            f"PROCESSED SIZE: "
            f"{processed_size} BYTES"
        )

        return processed_size

    finally:

        # ----------------------------------------------------
        # MEMORY CLEANUP
        # ----------------------------------------------------

        try:
            if source_image is not None:
                source_image.close()
        except Exception:
            pass

        try:
            if resized_image is not None:
                resized_image.close()
        except Exception:
            pass

        try:
            if output_image is not None:
                output_image.close()
        except Exception:
            pass

        source_image = None
        resized_image = None
        output_image = None

        cleanup_memory()

        print(
            f"MEMORY CLEANUP COMPLETE FOR: "
            f"{os.path.basename(source_path)}"
        )


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    return render_template(
        "index.html"
    )


# ============================================================
# RESIZE
# ============================================================

@app.route(
    "/resize",
    methods=["POST"]
)
def resize_image():

    files = request.files.getlist("image")

    files = [
        file
        for file in files
        if file and file.filename
    ]

    # --------------------------------------------------------
    # Check files
    # --------------------------------------------------------

    if not files:

        return render_template(
            "index.html",
            error="Please select at least one image."
        )


    if len(files) > MAX_FILES_PER_REQUEST:

        return render_template(
            "index.html",
            error=(
                f"You can process maximum "
                f"{MAX_FILES_PER_REQUEST} images at once."
            )
        )


    # --------------------------------------------------------
    # Get form data
    # --------------------------------------------------------

    width = request.form.get(
        "width",
        ""
    )

    height = request.form.get(
        "height",
        ""
    )

    quality = request.form.get(
        "quality",
        "80"
    )

    output_format = request.form.get(
        "format",
        "JPEG"
    )


    # --------------------------------------------------------
    # Validate numbers
    # --------------------------------------------------------

    try:

        width = int(width)
        height = int(height)
        quality = int(quality)

    except (ValueError, TypeError):

        return render_template(
            "index.html",
            error=(
                "Invalid width, height or quality."
            )
        )


    # --------------------------------------------------------
    # Validate dimensions
    # --------------------------------------------------------

    dimensions_ok, dimensions_error = (
        validate_dimensions(
            width,
            height
        )
    )

    if not dimensions_ok:

        return render_template(
            "index.html",
            error=dimensions_error
        )


    # --------------------------------------------------------
    # Validate quality
    # --------------------------------------------------------

    if quality < 10 or quality > 100:

        return render_template(
            "index.html",
            error=(
                "Quality must be between 10 and 100."
            )
        )


    # --------------------------------------------------------
    # Validate format
    # --------------------------------------------------------

    if output_format not in ALLOWED_FORMATS:

        return render_template(
            "index.html",
            error="Invalid output format."
        )


    # --------------------------------------------------------
    # Create batch
    # --------------------------------------------------------

    batch_id = uuid.uuid4().hex

    batch_folder = os.path.join(
        PROCESSED_FOLDER,
        batch_id
    )

    os.makedirs(
        batch_folder,
        exist_ok=True
    )


    processed_files = []
    comparison_data = []

    total_original_size = 0
    total_processed_size = 0


    # ========================================================
    # PROCESS FILES
    # ========================================================

    try:

        for index, file in enumerate(files):

            original_filename = secure_filename(
                file.filename
            )

            if not original_filename:
                continue


            # ------------------------------------------------
            # Validate extension
            # ------------------------------------------------

            input_extension = (
                os.path.splitext(
                    original_filename
                )[1]
                .lower()
                .replace(".", "")
            )

            if input_extension not in ALLOWED_EXTENSIONS:

                return render_template(
                    "index.html",
                    error=(
                        "Only JPG, JPEG, PNG and WEBP "
                        "images are allowed."
                    )
                )


            # ------------------------------------------------
            # Create unique filename
            # ------------------------------------------------

            original_name = os.path.splitext(
                original_filename
            )[0]

            if not original_name:
                original_name = "image"


            unique_name = (
                f"{original_name}_{index + 1}"
            )


            original_saved_name = (
                f"{unique_name}_original."
                f"{input_extension}"
            )


            original_path = os.path.join(
                UPLOAD_FOLDER,
                original_saved_name
            )


            # ------------------------------------------------
            # SAVE UPLOAD DIRECTLY TO DISK
            #
            # IMPORTANT:
            # Do NOT use file.read().
            # This prevents unnecessary memory usage.
            # ------------------------------------------------

            file.save(
                original_path
            )


            original_size_bytes = (
                os.path.getsize(
                    original_path
                )
            )

            total_original_size += (
                original_size_bytes
            )


            print(
                f"ORIGINAL FILE: "
                f"{original_path}"
            )

            print(
                f"ORIGINAL SIZE: "
                f"{original_size_bytes} BYTES"
            )


            # ------------------------------------------------
            # Validate image BEFORE loading pixels
            # ------------------------------------------------

            valid, validation_error, dimensions = (
                validate_uploaded_image(
                    original_path
                )
            )


            if not valid:

                print(
                    f"IMAGE VALIDATION ERROR: "
                    f"{validation_error}"
                )

                # Remove unsafe uploaded file
                safe_remove(
                    original_path
                )

                continue


            source_width, source_height = (
                dimensions
            )


            print(
                f"SOURCE DIMENSIONS: "
                f"{source_width} x {source_height}"
            )


            # ------------------------------------------------
            # Output filename
            # ------------------------------------------------

            output_extension = (
                ALLOWED_FORMATS[
                    output_format
                ]
            )


            output_name = (
                f"{unique_name}_processed."
                f"{output_extension}"
            )


            output_path = os.path.join(
                batch_folder,
                output_name
            )


            # ------------------------------------------------
            # Process
            # ------------------------------------------------

            try:

                processed_size = (
                    process_single_image(
                        source_path=original_path,
                        output_path=output_path,
                        width=width,
                        height=height,
                        quality=quality,
                        output_format=output_format
                    )
                )

            except Exception as error:

                print(
                    f"IMAGE PROCESSING ERROR: "
                    f"{repr(error)}"
                )

                safe_remove(
                    output_path
                )

                continue


            # ------------------------------------------------
            # Statistics
            # ------------------------------------------------

            total_processed_size += (
                processed_size
            )

            processed_files.append(
                output_name
            )


            comparison_data.append(
                {
                    "original": (
                        original_saved_name
                    ),

                    "processed": (
                        output_name
                    ),

                    "original_size": round(
                        original_size_bytes
                        / 1024,
                        2
                    ),

                    "processed_size": round(
                        processed_size
                        / 1024,
                        2
                    )
                }
            )


            # ------------------------------------------------
            # Cleanup after EACH image
            # ------------------------------------------------

            cleanup_memory()


        # ====================================================
        # NO SUCCESSFUL FILES
        # ====================================================

        if not processed_files:

            safe_remove(
                batch_folder
            )

            return render_template(
                "index.html",
                error=(
                    "No valid images could be processed. "
                    "For large images, use a smaller "
                    "source image or smaller output dimensions."
                )
            )


        # ====================================================
        # SAVED PERCENT
        # ====================================================

        if total_original_size > 0:

            saved_percent = round(
                (
                    (
                        total_original_size
                        - total_processed_size
                    )
                    / total_original_size
                ) * 100,
                2
            )

        else:

            saved_percent = 0


        # ====================================================
        # CREATE ZIP
        # ====================================================

        zip_name = (
            f"processed_images_{batch_id}.zip"
        )

        zip_path = os.path.join(
            PROCESSED_FOLDER,
            zip_name
        )


        try:

            with zipfile.ZipFile(
                zip_path,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6
            ) as zip_file:

                for filename in processed_files:

                    file_path = os.path.join(
                        batch_folder,
                        filename
                    )

                    if os.path.isfile(
                        file_path
                    ):

                        zip_file.write(
                            file_path,
                            arcname=filename
                        )


            print(
                f"ZIP CREATED: "
                f"{zip_path}"
            )

            print(
                f"ZIP SIZE: "
                f"{os.path.getsize(zip_path)} BYTES"
            )

        except Exception as error:

            print(
                f"ZIP ERROR: "
                f"{repr(error)}"
            )

            safe_remove(
                zip_path
            )

            zip_name = None


        # ====================================================
        # FINAL MEMORY CLEANUP
        # ====================================================

        cleanup_memory()


        # ====================================================
        # RESULT PAGE
        # ====================================================

        return render_template(
            "index.html",

            success=True,

            comparison_data=(
                comparison_data
            ),

            file_count=len(
                processed_files
            ),

            width=width,

            height=height,

            quality=quality,

            format=output_format,

            original_size=round(
                total_original_size / 1024,
                2
            ),

            compressed_size=round(
                total_processed_size / 1024,
                2
            ),

            saved_percent=saved_percent,

            zip_name=zip_name,

            batch_id=batch_id
        )


    except Exception as error:

        print(
            f"RESIZE ERROR: "
            f"{repr(error)}"
        )

        safe_remove(
            batch_folder
        )

        cleanup_memory()

        return render_template(
            "index.html",
            error=(
                "Image processing failed. "
                "Please try a smaller image."
            )
        )


# ============================================================
# DOWNLOAD ZIP
# ============================================================

@app.route(
    "/download/<filename>"
)
def download(filename):

    filename = secure_filename(
        filename
    )

    if not filename:
        abort(404)

    file_path = os.path.join(
        PROCESSED_FOLDER,
        filename
    )

    if not os.path.isfile(
        file_path
    ):
        abort(404)

    return send_from_directory(
        PROCESSED_FOLDER,
        filename,
        as_attachment=True
    )


# ============================================================
# SHOW ORIGINAL IMAGE
# ============================================================

@app.route(
    "/original/<filename>"
)
def original_image(filename):

    filename = secure_filename(
        filename
    )

    if not filename:
        abort(404)

    file_path = os.path.join(
        UPLOAD_FOLDER,
        filename
    )

    if not os.path.isfile(
        file_path
    ):
        abort(404)

    print(
        f"ORIGINAL REQUEST: "
        f"{file_path} "
        f"EXISTS: True"
    )

    return send_from_directory(
        UPLOAD_FOLDER,
        filename,
        as_attachment=False
    )


# ============================================================
# SHOW PROCESSED IMAGE
# ============================================================

@app.route(
    "/processed/<batch_id>/<filename>"
)
def processed_image(
    batch_id,
    filename
):

    # Prevent path traversal
    batch_id = secure_filename(
        batch_id
    )

    filename = secure_filename(
        filename
    )

    if not batch_id or not filename:
        abort(404)


    batch_folder = os.path.join(
        PROCESSED_FOLDER,
        batch_id
    )

    file_path = os.path.join(
        batch_folder,
        filename
    )


    if not os.path.isfile(
        file_path
    ):
        abort(404)


    print(
        f"PROCESSED REQUEST: "
        f"{file_path} "
        f"EXISTS: True"
    )


    return send_from_directory(
        batch_folder,
        filename,
        as_attachment=False
    )


# ============================================================
# DOWNLOAD INDIVIDUAL IMAGE
# ============================================================

@app.route(
    "/download-image/<batch_id>/<filename>"
)
def download_image(
    batch_id,
    filename
):

    batch_id = secure_filename(
        batch_id
    )

    filename = secure_filename(
        filename
    )

    if not batch_id or not filename:
        abort(404)


    batch_folder = os.path.join(
        PROCESSED_FOLDER,
        batch_id
    )

    file_path = os.path.join(
        batch_folder,
        filename
    )


    if not os.path.isfile(
        file_path
    ):
        abort(404)


    return send_from_directory(
        batch_folder,
        filename,
        as_attachment=True
    )


# ============================================================
# 413 ERROR - FILE TOO LARGE
# ============================================================

@app.errorhandler(413)
def request_entity_too_large(error):

    return render_template(
        "index.html",
        error=(
            "File is too large. "
            "Maximum upload size is 10 MB."
        )
    ), 413


# ============================================================
# 404
# ============================================================

@app.errorhandler(404)
def page_not_found(error):

    return render_template(
        "index.html",
        error="Requested file was not found."
    ), 404


# ============================================================
# GENERAL ERROR
# ============================================================

@app.errorhandler(500)
def internal_server_error(error):

    cleanup_memory()

    return render_template(
        "index.html",
        error=(
            "Server error occurred. "
            "Please try again with a smaller image."
        )
    ), 500


# ============================================================
# LOCAL DEVELOPMENT
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),
        debug=False,
        use_reloader=False
    )