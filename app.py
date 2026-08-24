import os
import uuid
import zipfile
import shutil
import webbrowser
import gc
import warnings

from flask import (
    Flask,
    render_template,
    request,
    send_from_directory
)

from PIL import (
    Image,
    ImageFile,
    UnidentifiedImageError
)

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
# SERVER UPLOAD LIMIT
# ============================================================

# 50 MB request limit.
# This prevents extremely large HTTP uploads from consuming
# too much memory/storage.
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024


# ============================================================
# CREATE DIRECTORIES
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
# PILLOW SAFETY SETTINGS
# ============================================================

# IMPORTANT:
# Do NOT use Image.MAX_IMAGE_PIXELS = None in production.
#
# Pillow's normal limit is useful as a security protection.
#
# We use our own application-level limit below.
Image.MAX_IMAGE_PIXELS = 60_000_000

# Do not allow incomplete/corrupted images to be processed.
ImageFile.LOAD_TRUNCATED_IMAGES = False

# Treat Pillow decompression-bomb warnings as errors.
warnings.simplefilter(
    "error",
    Image.DecompressionBombWarning
)


# ============================================================
# APPLICATION LIMITS
# ============================================================

# Maximum source image pixels accepted by this application.
#
# 60 million pixels allows:
#
# 8192 x 6144 = 50,331,648 pixels
#
# while still blocking extremely huge images.
MAX_SOURCE_PIXELS = 60_000_000


# Maximum output pixels.
#
# This is important because a user could upload a normal image
# but request something like:
#
# 20000 x 20000
#
# which itself would require a huge amount of memory.
MAX_OUTPUT_PIXELS = 25_000_000


# Maximum number of images in one request.
MAX_FILES_PER_REQUEST = 10


# ============================================================
# ALLOWED FILE TYPES
# ============================================================

ALLOWED_FORMATS = {
    "JPEG",
    "PNG",
    "WEBP"
}


ALLOWED_EXTENSIONS = {
    "jpg",
    "jpeg",
    "png",
    "webp"
}


# ============================================================
# HELPERS
# ============================================================

def format_kb(size_bytes):
    """
    Convert bytes to KB with 2 decimal places.
    """
    return round(
        size_bytes / 1024,
        2
    )


def cleanup_path(path):
    """
    Safely remove a file or directory.
    """
    try:

        if not path:
            return

        if os.path.isdir(path):

            shutil.rmtree(
                path,
                ignore_errors=True
            )

        elif os.path.exists(path):

            os.remove(path)

    except Exception as cleanup_error:

        print(
            "CLEANUP ERROR:",
            repr(cleanup_error)
        )


def cleanup_image(image):
    """
    Safely close a Pillow image.
    """
    try:

        if image is not None:

            image.close()

    except Exception:

        pass


def validate_dimensions(
    width,
    height
):
    """
    Validate requested output dimensions.
    """

    if width <= 0 or height <= 0:

        return (
            False,
            "Width and height must be greater than 0."
        )


    output_pixels = (
        width *
        height
    )


    if output_pixels > MAX_OUTPUT_PIXELS:

        return (
            False,
            (
                "Output dimensions are too large. "
                "Maximum supported output is "
                "25,000,000 pixels."
            )
        )


    return (
        True,
        None
    )


def get_safe_image_info(image_path):
    """
    Open image only for metadata validation.

    Returns:
        (image, width, height, format)

    Caller MUST close the returned image.
    """

    image = None

    try:

        image = Image.open(
            image_path,
            formats=[
                "JPEG",
                "PNG",
                "WEBP"
            ]
        )


        width, height = image.size


        if width <= 0 or height <= 0:

            raise ValueError(
                "Image has invalid dimensions."
            )


        pixels = (
            width *
            height
        )


        print(
            "SOURCE DIMENSIONS:",
            width,
            "x",
            height
        )

        print(
            "SOURCE PIXELS:",
            pixels
        )


        if pixels > MAX_SOURCE_PIXELS:

            raise ValueError(
                (
                    "This image is too large. "
                    "Maximum supported source image size is "
                    f"{MAX_SOURCE_PIXELS:,} pixels. "
                    f"Your image contains {pixels:,} pixels."
                )
            )


        return (
            image,
            width,
            height,
            image.format
        )


    except Exception:

        cleanup_image(
            image
        )

        raise


def prepare_image_for_resize(
    image,
    target_width,
    target_height
):
    """
    Prepare image safely for resizing.

    JPEG images can use draft() to reduce the amount of
    decoded data when the target is much smaller.

    Then load the image and convert it to RGB/RGBA.
    """

    # --------------------------------------------------------
    # JPEG draft decoding
    # --------------------------------------------------------

    if image.format == "JPEG":

        try:

            image.draft(
                "RGB",
                (
                    target_width,
                    target_height
                )
            )

        except Exception as draft_error:

            print(
                "JPEG DRAFT SKIPPED:",
                repr(draft_error)
            )


    # --------------------------------------------------------
    # Decode actual image data
    # --------------------------------------------------------

    image.load()


    # --------------------------------------------------------
    # Convert mode
    # --------------------------------------------------------

    if image.mode in (
        "RGBA",
        "LA",
        "P"
    ):

        converted = image.convert(
            "RGBA"
        )

    else:

        converted = image.convert(
            "RGB"
        )


    # If convert() returned a new image,
    # close the original decoded image.
    if converted is not image:

        try:

            image.close()

        except Exception:

            pass


    return converted


def resize_single_image(
    source_path,
    output_path,
    width,
    height,
    quality,
    output_format
):
    """
    Resize and save one image.

    Returns:
        processed_size_bytes
    """

    source_image = None
    working_image = None
    resized_image = None

    try:

        # ----------------------------------------------------
        # OPEN + VALIDATE
        # ----------------------------------------------------

        (
            source_image,
            source_width,
            source_height,
            source_format
        ) = get_safe_image_info(
            source_path
        )


        print(
            "IMAGE OPENED:",
            os.path.basename(source_path)
        )

        print(
            "IMAGE SIZE:",
            (
                source_width,
                source_height
            )
        )

        print(
            "IMAGE MODE:",
            source_image.mode
        )

        print(
            "IMAGE FORMAT:",
            source_format
        )


        # ----------------------------------------------------
        # PREPARE
        # ----------------------------------------------------

        working_image = prepare_image_for_resize(
            source_image,
            width,
            height
        )

        # source_image is already closed by
        # prepare_image_for_resize when needed.
        source_image = None


        # ----------------------------------------------------
        # RESIZE
        # ----------------------------------------------------

        resized_image = working_image.resize(
            (
                width,
                height
            ),
            Image.Resampling.BILINEAR
        )


        # ----------------------------------------------------
        # JPEG
        # ----------------------------------------------------

        if output_format == "JPEG":

            output_image = resized_image


            # JPEG does not support transparency.
            if output_image.mode != "RGB":

                background = Image.new(
                    "RGB",
                    output_image.size,
                    "white"
                )


                if (
                    "A" in
                    output_image.getbands()
                ):

                    alpha = (
                        output_image
                        .getchannel("A")
                    )


                    background.paste(
                        output_image,
                        mask=alpha
                    )


                    alpha.close()

                else:

                    background.paste(
                        output_image
                    )


                output_image = background


            try:

                output_image.save(
                    output_path,
                    "JPEG",
                    quality=quality,
                    optimize=False
                )

            finally:

                if output_image is not resized_image:

                    cleanup_image(
                        output_image
                    )


        # ----------------------------------------------------
        # PNG
        # ----------------------------------------------------

        elif output_format == "PNG":

            output_image = resized_image


            if output_image.mode not in (
                "RGB",
                "RGBA"
            ):

                output_image = (
                    output_image.convert(
                        "RGBA"
                    )
                )


            try:

                output_image.save(
                    output_path,
                    "PNG",
                    optimize=False
                )

            finally:

                if output_image is not resized_image:

                    cleanup_image(
                        output_image
                    )


        # ----------------------------------------------------
        # WEBP
        # ----------------------------------------------------

        elif output_format == "WEBP":

            output_image = resized_image


            if output_image.mode not in (
                "RGB",
                "RGBA"
            ):

                output_image = (
                    output_image.convert(
                        "RGB"
                    )
                )


            try:

                output_image.save(
                    output_path,
                    "WEBP",
                    quality=quality,
                    method=4
                )

            finally:

                if output_image is not resized_image:

                    cleanup_image(
                        output_image
                    )


        else:

            raise ValueError(
                "Unsupported output format."
            )


        # ----------------------------------------------------
        # VERIFY OUTPUT
        # ----------------------------------------------------

        if not os.path.exists(
            output_path
        ):

            raise Exception(
                "Processed image was not created."
            )


        processed_size = os.path.getsize(
            output_path
        )


        if processed_size <= 0:

            raise Exception(
                "Processed image is empty."
            )


        return processed_size


    finally:

        cleanup_image(
            resized_image
        )

        cleanup_image(
            working_image
        )

        cleanup_image(
            source_image
        )

        # Encourage Python/Pillow memory cleanup.
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
# RESIZE
# ============================================================

@app.route(
    "/resize",
    methods=["POST"]
)
def resize_image():

    batch_folder = None


    try:

        # ----------------------------------------------------
        # GET FILES
        # ----------------------------------------------------

        files = request.files.getlist(
            "image"
        )


        files = [
            file
            for file in files
            if file and file.filename
        ]


        if not files:

            return render_template(
                "index.html",
                error=(
                    "Please select at least one image."
                )
            )


        if len(files) > MAX_FILES_PER_REQUEST:

            return render_template(
                "index.html",
                error=(
                    f"Maximum {MAX_FILES_PER_REQUEST} "
                    "images can be processed at once."
                )
            )


        # ----------------------------------------------------
        # FORM VALUES
        # ----------------------------------------------------

        width_value = request.form.get(
            "width"
        )

        height_value = request.form.get(
            "height"
        )

        quality_value = request.form.get(
            "quality",
            "80"
        )

        output_format = request.form.get(
            "format",
            "JPEG"
        )


        try:

            width = int(
                width_value
            )

            height = int(
                height_value
            )

            quality = int(
                quality_value
            )

        except (
            ValueError,
            TypeError
        ):

            return render_template(
                "index.html",
                error=(
                    "Please enter valid width, "
                    "height and quality values."
                )
            )


        # ----------------------------------------------------
        # DIMENSION VALIDATION
        # ----------------------------------------------------

        valid_dimensions, dimension_error = (
            validate_dimensions(
                width,
                height
            )
        )


        if not valid_dimensions:

            return render_template(
                "index.html",
                error=dimension_error
            )


        # ----------------------------------------------------
        # QUALITY VALIDATION
        # ----------------------------------------------------

        if quality < 10 or quality > 100:

            return render_template(
                "index.html",
                error=(
                    "Compression quality must "
                    "be between 10 and 100."
                )
            )


        # ----------------------------------------------------
        # FORMAT VALIDATION
        # ----------------------------------------------------

        if output_format not in ALLOWED_FORMATS:

            return render_template(
                "index.html",
                error=(
                    "Please select a valid output format."
                )
            )


        # ----------------------------------------------------
        # BATCH
        # ----------------------------------------------------

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


        # ====================================================
        # PROCESS ONE IMAGE AT A TIME
        # ====================================================

        for index, file in enumerate(files):

            original_saved_name = None
            original_path = None


            try:

                # ------------------------------------------------
                # SECURE ORIGINAL NAME
                # ------------------------------------------------

                original_filename = secure_filename(
                    file.filename
                )


                if not original_filename:

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


                if (
                    input_extension
                    not in ALLOWED_EXTENSIONS
                ):

                    raise ValueError(
                        (
                            "Only JPG, JPEG, PNG and "
                            "WEBP images are allowed."
                        )
                    )


                # ------------------------------------------------
                # UNIQUE FILE NAME
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
                # SAVE ORIGINAL
                # ------------------------------------------------

                file.seek(0)

                file.save(
                    original_path
                )


                if not os.path.exists(
                    original_path
                ):

                    raise Exception(
                        "Original image could not be saved."
                    )


                original_size_bytes = (
                    os.path.getsize(
                        original_path
                    )
                )


                if original_size_bytes <= 0:

                    raise Exception(
                        "Original image is empty."
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


                # ------------------------------------------------
                # OUTPUT NAME
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
                # PROCESS
                # ------------------------------------------------

                processed_size = (
                    resize_single_image(
                        source_path=original_path,
                        output_path=output_path,
                        width=width,
                        height=height,
                        quality=quality,
                        output_format=output_format
                    )
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
                        format_kb(
                            original_size_bytes
                        ),

                    "processed_size":
                        format_kb(
                            processed_size
                        )
                })


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
                    original_filename
                )


                # ------------------------------------------------
                # MEMORY CLEANUP
                # ------------------------------------------------

                gc.collect()


            except Image.DecompressionBombError as bomb_error:

                print(
                    "IMAGE DECOMPRESSION ERROR:",
                    repr(bomb_error)
                )


                return render_template(
                    "index.html",
                    error=(
                        "This image is too large to "
                        "process safely. Please choose "
                        "a smaller image."
                    )
                )


            except Image.DecompressionBombWarning as warning_error:

                print(
                    "IMAGE DECOMPRESSION WARNING:",
                    repr(warning_error)
                )


                return render_template(
                    "index.html",
                    error=(
                        "This image is too large to "
                        "process safely."
                    )
                )


            except (
                UnidentifiedImageError,
                OSError
            ) as image_error:

                print(
                    "INVALID IMAGE:",
                    repr(image_error)
                )


                return render_template(
                    "index.html",
                    error=(
                        "One of the selected files is "
                        "not a valid JPG, PNG or WEBP image."
                    )
                )


            except ValueError as validation_error:

                print(
                    "IMAGE VALIDATION ERROR:",
                    repr(validation_error)
                )


                return render_template(
                    "index.html",
                    error=str(
                        validation_error
                    )
                )


            except Exception as image_error:

                print(
                    "IMAGE PROCESSING ERROR:",
                    repr(image_error)
                )


                return render_template(
                    "index.html",
                    error=(
                        "Unable to process one of the "
                        "selected images. Please try "
                        "a smaller image."
                    )
                )


            finally:

                # Close uploaded file handle.
                try:

                    file.close()

                except Exception:

                    pass


                gc.collect()


        # ====================================================
        # CHECK RESULT
        # ====================================================

        if not processed_files:

            cleanup_path(
                batch_folder
            )

            return render_template(
                "index.html",
                error=(
                    "No valid images were processed."
                )
            )


        # ====================================================
        # SPACE SAVED
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
                )
                * 100,
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
                        filename
                    )


        print(
            "ZIP CREATED:",
            zip_path
        )

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
        # SUCCESS
        # ====================================================

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
                format_kb(
                    total_original_size
                ),

            compressed_size=
                format_kb(
                    total_processed_size
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


        cleanup_path(
            batch_folder
        )


        gc.collect()


        return render_template(
            "index.html",
            error=(
                "Unable to process the images. "
                "Please try again with smaller images."
            )
        )


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
# HEALTH CHECK
# ============================================================

@app.route(
    "/health"
)
def health():

    return {
        "status": "ok"
    }, 200


# ============================================================
# LOCAL DEVELOPMENT
# ============================================================

if __name__ == "__main__":

    webbrowser.open(
        "http://127.0.0.1:5000"
    )


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