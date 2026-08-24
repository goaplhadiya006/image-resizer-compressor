import os
import uuid
import zipfile
import shutil
import gc
import webbrowser

from flask import (
    Flask,
    render_template,
    request,
    send_from_directory
)

from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename


app = Flask(__name__)


# ============================================================
# PATHS
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

UPLOAD_FOLDER = os.path.join(
    BASE_DIR,
    "uploads"
)

PROCESSED_FOLDER = os.path.join(
    BASE_DIR,
    "processed"
)


app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["PROCESSED_FOLDER"] = PROCESSED_FOLDER


# ============================================================
# FOLDERS
# ============================================================

os.makedirs(
    UPLOAD_FOLDER,
    exist_ok=True
)

os.makedirs(
    PROCESSED_FOLDER,
    exist_ok=True
)


# ============================================================
# SECURITY / MEMORY LIMITS
# ============================================================

# Do NOT use:
# Image.MAX_IMAGE_PIXELS = None
#
# Pillow's normal decompression-bomb protection remains enabled.

MAX_SOURCE_PIXELS = 60_000_000

# Maximum output dimensions allowed.
#
# This prevents somebody from requesting something like:
# 100000 x 100000
#
MAX_OUTPUT_WIDTH = 8000
MAX_OUTPUT_HEIGHT = 8000

MAX_OUTPUT_PIXELS = (
    MAX_OUTPUT_WIDTH *
    MAX_OUTPUT_HEIGHT
)


# Maximum number of images in one request.
MAX_FILES_PER_REQUEST = 20


# ============================================================
# ALLOWED FORMATS
# ============================================================

ALLOWED_FORMATS = [
    "JPEG",
    "PNG",
    "WEBP"
]


ALLOWED_EXTENSIONS = [
    "jpg",
    "jpeg",
    "png",
    "webp"
]


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def cleanup_folder(folder_path):
    """
    Safely remove a folder.
    """

    if not folder_path:
        return

    try:

        shutil.rmtree(
            folder_path,
            ignore_errors=True
        )

    except Exception as e:

        print(
            "CLEANUP ERROR:",
            repr(e)
        )


def format_error(message):
    """
    Render the main page with an error.
    """

    return render_template(
        "index.html",
        error=message
    )


def validate_extension(filename):
    """
    Check file extension.
    """

    extension = (
        os.path.splitext(filename)[1]
        .lower()
        .replace(".", "")
    )

    return extension in ALLOWED_EXTENSIONS


def calculate_target_size(
    source_width,
    source_height,
    requested_width,
    requested_height
):
    """
    Keep requested dimensions inside the configured
    output limits.

    If the requested dimensions are already safe,
    they are returned unchanged.

    Otherwise the dimensions are scaled down
    while maintaining the requested aspect ratio.
    """

    if requested_width <= 0:
        requested_width = 1

    if requested_height <= 0:
        requested_height = 1

    target_width = requested_width
    target_height = requested_height

    # --------------------------------------------------------
    # Dimension limit
    # --------------------------------------------------------

    if target_width > MAX_OUTPUT_WIDTH:

        scale = (
            MAX_OUTPUT_WIDTH /
            target_width
        )

        target_width = max(
            1,
            int(target_width * scale)
        )

        target_height = max(
            1,
            int(target_height * scale)
        )

    if target_height > MAX_OUTPUT_HEIGHT:

        scale = (
            MAX_OUTPUT_HEIGHT /
            target_height
        )

        target_width = max(
            1,
            int(target_width * scale)
        )

        target_height = max(
            1,
            int(target_height * scale)
        )

    # --------------------------------------------------------
    # Pixel limit
    # --------------------------------------------------------

    output_pixels = (
        target_width *
        target_height
    )

    if output_pixels > MAX_OUTPUT_PIXELS:

        scale = (
            MAX_OUTPUT_PIXELS /
            output_pixels
        ) ** 0.5

        target_width = max(
            1,
            int(target_width * scale)
        )

        target_height = max(
            1,
            int(target_height * scale)
        )

    return (
        target_width,
        target_height
    )


def open_image_safely(image_path):
    """
    Open image safely and validate its dimensions.

    The image is not fully loaded here.
    """

    try:

        image = Image.open(
            image_path
        )

    except (
        UnidentifiedImageError,
        OSError,
        ValueError
    ) as e:

        raise ValueError(
            "The uploaded file is not a valid image."
        ) from e

    width, height = image.size

    pixels = (
        width *
        height
    )

    print(
        "IMAGE OPENED:",
        os.path.basename(image_path)
    )

    print(
        "IMAGE SIZE:",
        image.size
    )

    print(
        "IMAGE MODE:",
        image.mode
    )

    print(
        "IMAGE FORMAT:",
        image.format
    )

    print(
        "IMAGE PIXELS:",
        pixels
    )

    # --------------------------------------------------------
    # Source image safety limit
    # --------------------------------------------------------

    if pixels > MAX_SOURCE_PIXELS:

        image.close()

        raise ValueError(
            "This image is too large to process safely. "
            f"Maximum supported image size is "
            f"{MAX_SOURCE_PIXELS:,} pixels. "
            f"Your image contains {pixels:,} pixels."
        )

    return image


def convert_for_output(image, output_format):
    """
    Convert image mode depending on output format.

    JPEG does not support transparency.
    """

    if output_format == "JPEG":

        if image.mode == "RGB":

            return image

        if image.mode in (
            "RGBA",
            "LA"
        ):

            background = Image.new(
                "RGB",
                image.size,
                "white"
            )

            if image.mode == "RGBA":

                background.paste(
                    image,
                    mask=image.getchannel(
                        "A"
                    )
                )

            else:

                alpha = image.getchannel(
                    "A"
                )

                background.paste(
                    image.convert("L"),
                    mask=alpha
                )

            return background

        if image.mode == "P":

            rgba = image.convert(
                "RGBA"
            )

            background = Image.new(
                "RGB",
                rgba.size,
                "white"
            )

            background.paste(
                rgba,
                mask=rgba.getchannel(
                    "A"
                )
            )

            rgba.close()

            return background

        return image.convert(
            "RGB"
        )

    # --------------------------------------------------------
    # PNG
    # --------------------------------------------------------

    if output_format == "PNG":

        if image.mode in (
            "RGB",
            "RGBA",
            "L",
            "LA"
        ):

            return image

        return image.convert(
            "RGBA"
        )

    # --------------------------------------------------------
    # WEBP
    # --------------------------------------------------------

    if output_format == "WEBP":

        if image.mode in (
            "RGB",
            "RGBA"
        ):

            return image

        return image.convert(
            "RGBA"
        )

    return image.convert(
        "RGB"
    )


def process_single_image(
    original_path,
    output_path,
    output_format,
    requested_width,
    requested_height,
    quality
):
    """
    Process one image with memory-conscious resizing.

    Important:
    We avoid loading a huge source image into a large
    intermediate resized image whenever possible.

    Pillow's thumbnail() works in-place and is useful for
    reducing a very large image before final resize.
    """

    source_image = None
    working_image = None
    output_image = None

    try:

        source_image = open_image_safely(
            original_path
        )

        source_width, source_height = (
            source_image.size
        )

        # ----------------------------------------------------
        # Calculate safe output dimensions
        # ----------------------------------------------------

        target_width, target_height = (
            calculate_target_size(
                source_width,
                source_height,
                requested_width,
                requested_height
            )
        )

        print(
            "TARGET SIZE:",
            target_width,
            "x",
            target_height
        )

        # ----------------------------------------------------
        # JPEG draft optimization
        # ----------------------------------------------------

        if source_image.format == "JPEG":

            try:

                source_image.draft(
                    "RGB",
                    (
                        target_width,
                        target_height
                    )
                )

            except Exception:

                pass

        # ----------------------------------------------------
        # Load source
        # ----------------------------------------------------

        source_image.load()

        # ----------------------------------------------------
        # Convert mode
        # ----------------------------------------------------

        if source_image.mode in (
            "RGBA",
            "LA",
            "P"
        ):

            working_image = source_image.convert(
                "RGBA"
            )

        else:

            working_image = source_image.convert(
                "RGB"
            )

        # Source object no longer needed.
        source_image.close()
        source_image = None

        # ----------------------------------------------------
        # Memory-conscious resize
        # ----------------------------------------------------

        # First use thumbnail to reduce very large images
        # close to the target.
        #
        # thumbnail() preserves aspect ratio.
        #
        thumbnail_limit = (
            target_width,
            target_height
        )

        if (
            working_image.width > target_width
            or
            working_image.height > target_height
        ):

            working_image.thumbnail(
                thumbnail_limit,
                Image.Resampling.BILINEAR
            )

        # ----------------------------------------------------
        # Final exact resize
        # ----------------------------------------------------

        if (
            working_image.width != target_width
            or
            working_image.height != target_height
        ):

            output_image = working_image.resize(
                (
                    target_width,
                    target_height
                ),
                Image.Resampling.BILINEAR
            )

        else:

            output_image = working_image

        # If output_image is the same object as working_image,
        # don't close it twice later.
        same_object = (
            output_image is working_image
        )

        # ----------------------------------------------------
        # Prepare output format
        # ----------------------------------------------------

        converted_image = convert_for_output(
            output_image,
            output_format
        )

        converted_same_object = (
            converted_image is output_image
        )

        # ----------------------------------------------------
        # SAVE JPEG
        # ----------------------------------------------------

        if output_format == "JPEG":

            converted_image.save(
                output_path,
                format="JPEG",
                quality=quality,
                optimize=False,
                progressive=True
            )

        # ----------------------------------------------------
        # SAVE PNG
        # ----------------------------------------------------

        elif output_format == "PNG":

            converted_image.save(
                output_path,
                format="PNG",
                optimize=False
            )

        # ----------------------------------------------------
        # SAVE WEBP
        # ----------------------------------------------------

        else:

            converted_image.save(
                output_path,
                format="WEBP",
                quality=quality,
                method=4
            )

        # ----------------------------------------------------
        # Cleanup converted image
        # ----------------------------------------------------

        if not converted_same_object:

            try:

                converted_image.close()

            except Exception:

                pass

        # ----------------------------------------------------
        # Cleanup output image
        # ----------------------------------------------------

        if not same_object:

            try:

                output_image.close()

            except Exception:

                pass

        # ----------------------------------------------------
        # Cleanup working image
        # ----------------------------------------------------

        try:

            working_image.close()

        except Exception:

            pass

        working_image = None
        output_image = None

        gc.collect()

        if not os.path.exists(output_path):

            raise ValueError(
                "Processed image was not created."
            )

        processed_size = os.path.getsize(
            output_path
        )

        if processed_size <= 0:

            raise ValueError(
                "Processed image is empty."
            )

        print(
            "PROCESSED FILE:",
            output_path
        )

        print(
            "PROCESSED SIZE:",
            processed_size,
            "BYTES"
        )

        print(
            "MEMORY CLEANUP COMPLETE FOR:",
            os.path.basename(original_path)
        )

        return (
            target_width,
            target_height,
            processed_size
        )

    except Exception:

        # ----------------------------------------------------
        # Emergency cleanup
        # ----------------------------------------------------

        if source_image is not None:

            try:

                source_image.close()

            except Exception:

                pass

        if output_image is not None:

            try:

                output_image.close()

            except Exception:

                pass

        if working_image is not None:

            try:

                working_image.close()

            except Exception:

                pass

        gc.collect()

        raise


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    return render_template(
        "index.html"
    )


# ============================================================
# RESIZE / COMPRESS
# ============================================================

@app.route(
    "/resize",
    methods=["POST"]
)
def resize_image():

    files = request.files.getlist(
        "image"
    )

    files = [
        file
        for file in files
        if file and file.filename
    ]

    # --------------------------------------------------------
    # No files
    # --------------------------------------------------------

    if not files:

        return format_error(
            "Please select at least one image."
        )

    # --------------------------------------------------------
    # Maximum file count
    # --------------------------------------------------------

    if len(files) > MAX_FILES_PER_REQUEST:

        return format_error(
            f"You can process maximum "
            f"{MAX_FILES_PER_REQUEST} images at once."
        )

    # --------------------------------------------------------
    # Get form values
    # --------------------------------------------------------

    width = request.form.get(
        "width"
    )

    height = request.form.get(
        "height"
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

    except (
        ValueError,
        TypeError
    ):

        return format_error(
            "Please enter valid width, height and quality values."
        )

    # --------------------------------------------------------
    # Validate dimensions
    # --------------------------------------------------------

    if width <= 0 or height <= 0:

        return format_error(
            "Width and height must be greater than 0."
        )

    # --------------------------------------------------------
    # Validate quality
    # --------------------------------------------------------

    if quality < 10 or quality > 100:

        return format_error(
            "Compression quality must be between 10 and 100."
        )

    # --------------------------------------------------------
    # Validate output format
    # --------------------------------------------------------

    if output_format not in ALLOWED_FORMATS:

        return format_error(
            "Please select a valid output format."
        )

    # --------------------------------------------------------
    # Protect against huge output requests
    # --------------------------------------------------------

    safe_width, safe_height = (
        calculate_target_size(
            1,
            1,
            width,
            height
        )
    )

    # --------------------------------------------------------
    # Create batch
    # --------------------------------------------------------

    batch_id = uuid.uuid4().hex

    batch_folder = os.path.join(
        app.config["PROCESSED_FOLDER"],
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

    successful_count = 0

    # --------------------------------------------------------
    # Process files
    # --------------------------------------------------------

    try:

        for index, file in enumerate(files):

            original_filename = secure_filename(
                file.filename
            )

            if not original_filename:

                continue

            # ------------------------------------------------
            # Extension validation
            # ------------------------------------------------

            if not validate_extension(
                original_filename
            ):

                print(
                    "INVALID EXTENSION:",
                    original_filename
                )

                continue

            input_extension = (
                os.path.splitext(
                    original_filename
                )[1]
                .lower()
                .replace(
                    ".",
                    ""
                )
            )

            # ------------------------------------------------
            # Unique names
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
                unique_name
                + "_original."
                + input_extension
            )

            original_path = os.path.join(
                app.config["UPLOAD_FOLDER"],
                original_saved_name
            )

            # ------------------------------------------------
            # Save original
            # ------------------------------------------------

            file.seek(0)

            file.save(
                original_path
            )

            if not os.path.exists(
                original_path
            ):

                print(
                    "ORIGINAL FILE NOT CREATED:",
                    original_filename
                )

                continue

            original_size_bytes = (
                os.path.getsize(
                    original_path
                )
            )

            if original_size_bytes <= 0:

                print(
                    "EMPTY ORIGINAL FILE:",
                    original_filename
                )

                continue

            total_original_size += (
                original_size_bytes
            )

            print(
                "ORIGINAL FILE:",
                original_path
            )

            print(
                "ORIGINAL SIZE:",
                original_size_bytes,
                "BYTES"
            )

            # ------------------------------------------------
            # Output filename
            # ------------------------------------------------

            if output_format == "JPEG":

                output_name = (
                    unique_name
                    + "_processed.jpg"
                )

            elif output_format == "PNG":

                output_name = (
                    unique_name
                    + "_processed.png"
                )

            else:

                output_name = (
                    unique_name
                    + "_processed.webp"
                )

            output_path = os.path.join(
                batch_folder,
                output_name
            )

            # ------------------------------------------------
            # Process
            # ------------------------------------------------

            try:

                (
                    final_width,
                    final_height,
                    processed_size
                ) = process_single_image(
                    original_path,
                    output_path,
                    output_format,
                    safe_width,
                    safe_height,
                    quality
                )

            except Exception as image_error:

                print(
                    "IMAGE PROCESSING ERROR:",
                    repr(image_error)
                )

                # Remove invalid processed file
                if os.path.exists(
                    output_path
                ):

                    try:

                        os.remove(
                            output_path
                        )

                    except Exception:

                        pass

                gc.collect()

                continue

            # ------------------------------------------------
            # Count processed
            # ------------------------------------------------

            total_processed_size += (
                processed_size
            )

            successful_count += 1

            processed_files.append(
                output_name
            )

            comparison_data.append({

                "original":
                    original_saved_name,

                "processed":
                    output_name,

                "original_size":
                    round(
                        original_size_bytes / 1024,
                        2
                    ),

                "processed_size":
                    round(
                        processed_size / 1024,
                        2
                    )
            })

            # ------------------------------------------------
            # Memory cleanup after EVERY image
            # ------------------------------------------------

            gc.collect()

        # ====================================================
        # No successful images
        # ====================================================

        if not processed_files:

            cleanup_folder(
                batch_folder
            )

            gc.collect()

            return format_error(
                "No valid images could be processed. "
                "Please select JPG, PNG or WEBP images."
            )

        # ====================================================
        # Calculate saved percentage
        # ====================================================

        if total_original_size > 0:

            saved_percent = round(
                (
                    (
                        total_original_size
                        -
                        total_processed_size
                    )
                    /
                    total_original_size
                ) * 100,
                2
            )

        else:

            saved_percent = 0

        # ====================================================
        # CREATE ZIP
        # ====================================================

        zip_name = (
            "processed_images_"
            + batch_id
            + ".zip"
        )

        zip_path = os.path.join(
            app.config["PROCESSED_FOLDER"],
            zip_name
        )

        with zipfile.ZipFile(
            zip_path,
            "w",
            compression=zipfile.ZIP_DEFLATED
        ) as zip_file:

            for filename in processed_files:

                file_path = os.path.join(
                    batch_folder,
                    filename
                )

                if os.path.exists(
                    file_path
                ):

                    zip_file.write(
                        file_path,
                        arcname=filename
                    )

        print(
            "ZIP CREATED:",
            zip_path
        )

        if os.path.exists(
            zip_path
        ):

            print(
                "ZIP SIZE:",
                os.path.getsize(
                    zip_path
                )
            )

        # ====================================================
        # FINAL MEMORY CLEANUP
        # ====================================================

        gc.collect()

        # ====================================================
        # SUCCESS RESPONSE
        # ====================================================

        return render_template(

            "index.html",

            success=True,

            comparison_data=
                comparison_data,

            file_count=
                successful_count,

            width=
                safe_width,

            height=
                safe_height,

            quality=
                quality,

            format=
                output_format,

            original_size=
                round(
                    total_original_size / 1024,
                    2
                ),

            compressed_size=
                round(
                    total_processed_size / 1024,
                    2
                ),

            saved_percent=
                saved_percent,

            zip_name=
                zip_name,

            batch_id=
                batch_id
        )

    except Exception as e:

        print(
            "BATCH PROCESSING ERROR:",
            repr(e)
        )

        cleanup_folder(
            batch_folder
        )

        gc.collect()

        return render_template(
            "index.html",
            error=(
                "Unable to process the images. "
                "Please try again with valid image files."
            )
        ), 500


# ============================================================
# DOWNLOAD ZIP
# ============================================================

@app.route(
    "/download/<filename>"
)
def download(filename):

    return send_from_directory(
        app.config["PROCESSED_FOLDER"],
        filename,
        as_attachment=True
    )


# ============================================================
# ORIGINAL IMAGE
# ============================================================

@app.route(
    "/original/<filename>"
)
def original_image(filename):

    file_path = os.path.join(
        app.config["UPLOAD_FOLDER"],
        filename
    )

    print(
        "ORIGINAL REQUEST:",
        file_path,
        "EXISTS:",
        os.path.exists(file_path)
    )

    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename,
        conditional=False
    )


# ============================================================
# PROCESSED IMAGE
# ============================================================

@app.route(
    "/processed/<batch_id>/<filename>"
)
def processed_image(
    batch_id,
    filename
):

    batch_folder = os.path.join(
        app.config["PROCESSED_FOLDER"],
        batch_id
    )

    file_path = os.path.join(
        batch_folder,
        filename
    )

    print(
        "PROCESSED REQUEST:",
        file_path,
        "EXISTS:",
        os.path.exists(file_path)
    )

    return send_from_directory(
        batch_folder,
        filename,
        conditional=False
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

    batch_folder = os.path.join(
        app.config["PROCESSED_FOLDER"],
        batch_id
    )

    file_path = os.path.join(
        batch_folder,
        filename
    )

    print(
        "IMAGE DOWNLOAD:",
        file_path,
        "EXISTS:",
        os.path.exists(file_path)
    )

    return send_from_directory(
        batch_folder,
        filename,
        as_attachment=True
    )


# ============================================================
# LOCAL DEVELOPMENT
# ============================================================

if __name__ == "__main__":

    webbrowser.open(
        "http://127.0.0.1:5000"
    )

    app.run(
        debug=True,
        use_reloader=False
    )