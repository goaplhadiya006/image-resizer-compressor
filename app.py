import os
import uuid
import zipfile
import shutil
import webbrowser
import gc

from flask import Flask, render_template, request, send_from_directory
from PIL import Image
from werkzeug.utils import secure_filename


app = Flask(__name__)


# ============================================================
# BASE DIRECTORIES
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

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
# UPLOAD SETTINGS
# ============================================================

# Maximum HTTP request size.
# This is only the uploaded file size.
# It does NOT mean the image will consume this much RAM.
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024


# Create folders
os.makedirs(
    UPLOAD_FOLDER,
    exist_ok=True
)

os.makedirs(
    PROCESSED_FOLDER,
    exist_ok=True
)


# ============================================================
# IMAGE SAFETY SETTINGS
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


# Maximum output pixels.
#
# Example:
# 4000 x 4000 = 16,000,000 pixels
#
# This prevents users from requesting extremely large
# output images that could consume a lot of RAM.
MAX_OUTPUT_PIXELS = 16_000_000


# JPEG files can safely be processed above Pillow's normal
# DecompressionBomb limit when we first downsample them
# using JPEG draft mode.
#
# We still put a hard upper limit to protect the server.
MAX_JPEG_SOURCE_PIXELS = 80_000_000


# PNG/WEBP normally do not have JPEG-style draft decoding.
# Therefore we use a lower safe source-pixel limit for them.
MAX_OTHER_SOURCE_PIXELS = 30_000_000


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def safe_error(message):
    """
    Render the normal page with an error message.
    """

    return render_template(
        "index.html",
        error=message
    )


def format_extension(filename):
    """
    Return the lowercase file extension without dot.
    """

    return (
        os.path.splitext(filename)[1]
        .lower()
        .replace(".", "")
    )


def calculate_safe_draft_size(
    source_width,
    source_height,
    target_width,
    target_height
):
    """
    Calculate a reasonable draft decoding size.

    JPEG draft() supports approximate powers of two:
        1/2
        1/4
        1/8

    We select the smallest useful source resolution
    that is still large enough for the requested output.
    """

    target_width = max(
        1,
        int(target_width)
    )

    target_height = max(
        1,
        int(target_height)
    )

    # If source is already smaller than requested,
    # don't downsample.
    if (
        source_width <= target_width
        and source_height <= target_height
    ):
        return (
            source_width,
            source_height
        )

    # Calculate approximate scale.
    scale_x = (
        target_width /
        float(source_width)
    )

    scale_y = (
        target_height /
        float(source_height)
    )

    scale = min(
        scale_x,
        scale_y
    )

    # We want enough pixels for the target.
    # JPEG draft uses 1, 1/2, 1/4 or 1/8.
    if scale >= 0.75:

        return (
            source_width,
            source_height
        )

    elif scale >= 0.375:

        return (
            max(1, source_width // 2),
            max(1, source_height // 2)
        )

    elif scale >= 0.1875:

        return (
            max(1, source_width // 4),
            max(1, source_height // 4)
        )

    else:

        return (
            max(1, source_width // 8),
            max(1, source_height // 8)
        )


def validate_dimensions(
    width,
    height
):
    """
    Validate requested output dimensions.
    """

    if width <= 0 or height <= 0:

        return False

    output_pixels = (
        width *
        height
    )

    if output_pixels > MAX_OUTPUT_PIXELS:

        return False

    return True


def cleanup_batch(batch_folder):
    """
    Delete a processed batch folder safely.
    """

    if not batch_folder:

        return

    try:

        if os.path.exists(batch_folder):

            shutil.rmtree(
                batch_folder,
                ignore_errors=True
            )

    except Exception as e:

        print(
            "BATCH CLEANUP ERROR:",
            repr(e)
        )


def cleanup_memory(*objects):
    """
    Close PIL objects and force garbage collection.
    """

    for obj in objects:

        try:

            if obj is not None:

                obj.close()

        except Exception:

            pass

    gc.collect()


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

    if not files:

        return safe_error(
            "Please select at least one image."
        )


    # --------------------------------------------------------
    # GET FORM VALUES
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
    # VALIDATE FORM VALUES
    # --------------------------------------------------------

    try:

        width = int(width)

        height = int(height)

        quality = int(quality)

    except (
        ValueError,
        TypeError
    ):

        return safe_error(
            "Please enter valid width, height and quality values."
        )


    if not validate_dimensions(
        width,
        height
    ):

        return safe_error(
            "Output dimensions are too large. Maximum supported output is 16 megapixels."
        )


    if quality < 10 or quality > 100:

        return safe_error(
            "Compression quality must be between 10 and 100."
        )


    if output_format not in ALLOWED_FORMATS:

        return safe_error(
            "Please select a valid output format."
        )


    # --------------------------------------------------------
    # CREATE BATCH
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


    # ========================================================
    # PROCESS ONE IMAGE AT A TIME
    # ========================================================

    try:

        for index, file in enumerate(files):

            image = None

            resized_image = None

            converted_image = None


            try:

                # ------------------------------------------------
                # SECURE FILE NAME
                # ------------------------------------------------

                original_filename = secure_filename(
                    file.filename
                )


                if not original_filename:

                    continue


                input_extension = format_extension(
                    original_filename
                )


                # ------------------------------------------------
                # VALIDATE EXTENSION
                # ------------------------------------------------

                if input_extension not in ALLOWED_EXTENSIONS:

                    raise ValueError(
                        "Only JPG, JPEG, PNG and WEBP images are allowed."
                    )


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
                # SAVE ORIGINAL DIRECTLY TO DISK
                # ------------------------------------------------

                file.seek(0)

                file.save(
                    original_path
                )


                if not os.path.exists(
                    original_path
                ):

                    raise ValueError(
                        "Original image could not be saved."
                    )


                original_size_bytes = os.path.getsize(
                    original_path
                )


                if original_size_bytes <= 0:

                    raise ValueError(
                        "Original image was saved as an empty file."
                    )


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


                # =================================================
                # OPEN IMAGE
                # =================================================

                image = Image.open(
                    original_path
                )


                source_width = image.width

                source_height = image.height

                source_pixels = (
                    source_width *
                    source_height
                )


                source_mode = image.mode

                source_format = image.format


                print(
                    "IMAGE OPENED:",
                    original_filename
                )

                print(
                    "IMAGE SIZE:",
                    image.size
                )

                print(
                    "IMAGE MODE:",
                    source_mode
                )

                print(
                    "IMAGE FORMAT:",
                    source_format
                )

                print(
                    "SOURCE DIMENSIONS:",
                    source_width,
                    "x",
                    source_height
                )

                print(
                    "SOURCE PIXELS:",
                    source_pixels
                )


                # =================================================
                # SOURCE IMAGE SAFETY
                # =================================================

                if source_format == "JPEG":

                    # ------------------------------------------------
                    # JPEG
                    #
                    # Large JPEGs can be safely downsampled using
                    # Pillow's draft decoder before image.load().
                    # ------------------------------------------------

                    if source_pixels > MAX_JPEG_SOURCE_PIXELS:

                        raise ValueError(
                            "This JPEG image is too large to process safely. "
                            "Maximum supported source size is "
                            f"{MAX_JPEG_SOURCE_PIXELS:,} pixels."
                        )


                    # ------------------------------------------------
                    # IMPORTANT:
                    #
                    # draft() is applied BEFORE load().
                    #
                    # This is the main memory optimization.
                    # ------------------------------------------------

                    draft_width, draft_height = (
                        calculate_safe_draft_size(
                            source_width,
                            source_height,
                            width,
                            height
                        )
                    )


                    try:

                        image.draft(
                            "RGB",
                            (
                                draft_width,
                                draft_height
                            )
                        )

                        print(
                            "JPEG DRAFT SIZE:",
                            draft_width,
                            "x",
                            draft_height
                        )

                    except Exception as draft_error:

                        print(
                            "JPEG DRAFT WARNING:",
                            repr(draft_error)
                        )


                else:

                    # ------------------------------------------------
                    # PNG / WEBP
                    #
                    # These formats don't have the same JPEG draft
                    # decoding mechanism.
                    # ------------------------------------------------

                    if source_pixels > MAX_OTHER_SOURCE_PIXELS:

                        raise ValueError(
                            "This "
                            + str(source_format)
                            + " image is too large to process safely. "
                            "Maximum supported size for this format is "
                            f"{MAX_OTHER_SOURCE_PIXELS:,} pixels."
                        )


                # =================================================
                # LOAD IMAGE
                # =================================================

                image.load()


                # ------------------------------------------------
                # Print actual decoded size after draft()
                # ------------------------------------------------

                print(
                    "DECODED IMAGE SIZE:",
                    image.size
                )


                # =================================================
                # CONVERT MODE ONLY WHEN REQUIRED
                # =================================================

                if output_format == "JPEG":

                    # JPEG cannot store transparency.

                    if image.mode != "RGB":

                        converted_image = image.convert(
                            "RGB"
                        )

                        image.close()

                        image = None

                        image = converted_image

                        converted_image = None


                elif output_format == "PNG":

                    if image.mode not in (
                        "RGB",
                        "RGBA"
                    ):

                        converted_image = image.convert(
                            "RGBA"
                        )

                        image.close()

                        image = None

                        image = converted_image

                        converted_image = None


                else:

                    # WEBP supports RGB/RGBA.
                    if image.mode not in (
                        "RGB",
                        "RGBA"
                    ):

                        converted_image = image.convert(
                            "RGB"
                        )

                        image.close()

                        image = None

                        image = converted_image

                        converted_image = None


                # =================================================
                # RESIZE
                # =================================================

                resized_image = image.resize(
                    (
                        width,
                        height
                    ),
                    Image.Resampling.BILINEAR
                )


                # =================================================
                # OUTPUT FILE
                # =================================================

                if output_format == "JPEG":

                    output_name = (
                        unique_name
                        + "_processed.jpg"
                    )

                    output_path = os.path.join(
                        batch_folder,
                        output_name
                    )


                    # Ensure RGB.
                    if resized_image.mode != "RGB":

                        converted_image = resized_image.convert(
                            "RGB"
                        )

                        resized_image.close()

                        resized_image = None

                        resized_image = converted_image

                        converted_image = None


                    resized_image.save(
                        output_path,
                        "JPEG",
                        quality=quality,
                        optimize=False
                    )


                elif output_format == "PNG":

                    output_name = (
                        unique_name
                        + "_processed.png"
                    )

                    output_path = os.path.join(
                        batch_folder,
                        output_name
                    )


                    if resized_image.mode not in (
                        "RGB",
                        "RGBA"
                    ):

                        converted_image = resized_image.convert(
                            "RGBA"
                        )

                        resized_image.close()

                        resized_image = None

                        resized_image = converted_image

                        converted_image = None


                    resized_image.save(
                        output_path,
                        "PNG",
                        optimize=False
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


                    if resized_image.mode not in (
                        "RGB",
                        "RGBA"
                    ):

                        converted_image = resized_image.convert(
                            "RGB"
                        )

                        resized_image.close()

                        resized_image = None

                        resized_image = converted_image

                        converted_image = None


                    resized_image.save(
                        output_path,
                        "WEBP",
                        quality=quality,
                        method=4
                    )


                # =================================================
                # VERIFY OUTPUT
                # =================================================

                if not os.path.exists(
                    output_path
                ):

                    raise ValueError(
                        "Processed image was not created."
                    )


                processed_size = os.path.getsize(
                    output_path
                )


                if processed_size <= 0:

                    raise ValueError(
                        "Processed image was created as an empty file."
                    )


                total_processed_size += (
                    processed_size
                )


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


                print(
                    "PROCESSED FILE:",
                    output_path
                )

                print(
                    "PROCESSED FILE SIZE:",
                    processed_size,
                    "BYTES"
                )


            except Exception as image_error:

                print(
                    "IMAGE PROCESSING ERROR:",
                    repr(image_error)
                )


                # If one image is invalid, continue with
                # the remaining images.
                continue


            finally:

                # =================================================
                # VERY IMPORTANT MEMORY CLEANUP
                # =================================================

                try:

                    if converted_image is not None:

                        converted_image.close()

                except Exception:

                    pass


                try:

                    if resized_image is not None:

                        resized_image.close()

                except Exception:

                    pass


                try:

                    if image is not None:

                        image.close()

                except Exception:

                    pass


                image = None

                resized_image = None

                converted_image = None


                # Force Python garbage collection.
                gc.collect()


                print(
                    "MEMORY CLEANUP COMPLETE FOR:",
                    original_filename
                    if "original_filename" in locals()
                    else "image"
                )


        # ========================================================
        # CHECK RESULTS
        # ========================================================

        if not processed_files:

            cleanup_batch(
                batch_folder
            )


            return safe_error(
                "No valid images could be processed. "
                "The selected image may be too large or unsupported."
            )


        # ========================================================
        # SPACE SAVED
        # ========================================================

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
                )
                * 100,
                2
            )

        else:

            saved_percent = 0


        # ========================================================
        # CREATE ZIP
        # ========================================================

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
            zipfile.ZIP_DEFLATED
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
                        filename
                    )


        print(
            "ZIP CREATED:",
            zip_path
        )

        print(
            "ZIP SIZE:",
            os.path.getsize(zip_path),
            "BYTES"
        )


        # ========================================================
        # FINAL MEMORY CLEANUP
        # ========================================================

        gc.collect()


        # ========================================================
        # RETURN RESULT PAGE
        # ========================================================

        return render_template(

            "index.html",

            success=True,

            comparison_data=
                comparison_data,

            file_count=
                len(processed_files),

            width=
                width,

            height=
                height,

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
            "GENERAL PROCESSING ERROR:",
            repr(e)
        )


        cleanup_batch(
            batch_folder
        )


        gc.collect()


        return render_template(
            "index.html",
            error=(
                "Unable to process the images. "
                "Please try another image."
            )
        ), 500


# ============================================================
# DOWNLOAD ZIP
# ============================================================

@app.route(
    "/download/<filename>"
)
def download(filename):

    file_path = os.path.join(
        app.config["PROCESSED_FOLDER"],
        filename
    )


    print(
        "ZIP DOWNLOAD:",
        file_path,
        "EXISTS:",
        os.path.exists(file_path)
    )


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
        os.path.exists(file_path),
        "SIZE:",
        (
            os.path.getsize(file_path)
            if os.path.exists(file_path)
            else 0
        )
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
        os.path.exists(file_path),
        "SIZE:",
        (
            os.path.getsize(file_path)
            if os.path.exists(file_path)
            else 0
        )
    )


    return send_from_directory(
        batch_folder,
        filename,
        conditional=False
    )


# ============================================================
# INDIVIDUAL IMAGE DOWNLOAD
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
        os.path.exists(file_path),
        "SIZE:",
        (
            os.path.getsize(file_path)
            if os.path.exists(file_path)
            else 0
        )
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