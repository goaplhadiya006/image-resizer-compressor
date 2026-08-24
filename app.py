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
# MEMORY / UPLOAD SAFETY
# ============================================================

# Do NOT remove the pixel limit.
#
# A compressed JPG can be only a few MB but can expand to
# hundreds of MB when decoded into RAM.
#
# 30 million pixels is a safer limit for small Render instances.
#
# Example:
# 6000 x 5000 = 30,000,000 pixels
#
# 7000 x 7000 = 49,000,000 pixels -> rejected.
#
MAX_IMAGE_PIXELS = 30_000_000

Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


# Optional request upload limit.
#
# This prevents extremely large HTTP uploads from consuming
# unnecessary server resources.
#
# 30 MB is enough for normal image-resizer usage.
#
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024


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
# ALLOWED FILE TYPES
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
    Safely delete a folder.
    """

    try:

        if os.path.exists(folder_path):

            shutil.rmtree(
                folder_path,
                ignore_errors=True
            )

    except Exception as e:

        print(
            "CLEANUP ERROR:",
            repr(e)
        )


def cleanup_file(file_path):
    """
    Safely delete a file.
    """

    try:

        if (
            file_path
            and
            os.path.exists(file_path)
        ):

            os.remove(
                file_path
            )

    except Exception as e:

        print(
            "FILE CLEANUP ERROR:",
            repr(e)
        )


def validate_image_dimensions(
    image,
    width,
    height
):
    """
    Validate source image dimensions before
    doing expensive processing.
    """

    source_width, source_height = image.size

    pixel_count = (
        source_width *
        source_height
    )

    print(
        "SOURCE DIMENSIONS:",
        source_width,
        "x",
        source_height
    )

    print(
        "SOURCE PIXELS:",
        pixel_count
    )

    print(
        "MAX ALLOWED PIXELS:",
        MAX_IMAGE_PIXELS
    )

    if pixel_count > MAX_IMAGE_PIXELS:

        raise ValueError(
            "This image is too large to process safely. "
            f"Maximum supported image size is "
            f"{MAX_IMAGE_PIXELS:,} pixels. "
            f"Your image contains {pixel_count:,} pixels."
        )

    if width <= 0 or height <= 0:

        raise ValueError(
            "Width and height must be greater than 0."
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
# RESIZE IMAGE
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
        if file
        and file.filename
    ]

    if not files:

        return render_template(
            "index.html",
            error="Please select at least one image."
        )


    # ========================================================
    # GET FORM VALUES
    # ========================================================

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


    # ========================================================
    # VALIDATE FORM VALUES
    # ========================================================

    try:

        width = int(
            width
        )

        height = int(
            height
        )

        quality = int(
            quality
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


    if width <= 0 or height <= 0:

        return render_template(
            "index.html",
            error=(
                "Width and height must be greater than 0."
            )
        )


    if quality < 10 or quality > 100:

        return render_template(
            "index.html",
            error=(
                "Compression quality must be "
                "between 10 and 100."
            )
        )


    if output_format not in ALLOWED_FORMATS:

        return render_template(
            "index.html",
            error=(
                "Please select a valid output format."
            )
        )


    # ========================================================
    # CREATE BATCH
    # ========================================================

    batch_id = uuid.uuid4().hex

    batch_folder = os.path.join(
        app.config["PROCESSED_FOLDER"],
        batch_id
    )

    os.makedirs(
        batch_folder,
        exist_ok=True
    )


    # ========================================================
    # PROCESSING VARIABLES
    # ========================================================

    processed_files = []

    comparison_data = []

    total_original_size = 0

    total_processed_size = 0

    saved_original_files = []


    # ========================================================
    # PROCESS IMAGES ONE BY ONE
    # ========================================================

    try:

        for index, file in enumerate(files):

            original_filename = secure_filename(
                file.filename
            )


            if not original_filename:

                continue


            # =================================================
            # CHECK EXTENSION
            # =================================================

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
                not in
                ALLOWED_EXTENSIONS
            ):

                cleanup_folder(
                    batch_folder
                )

                return render_template(
                    "index.html",
                    error=(
                        "Only JPG, JPEG, PNG and WEBP "
                        "images are allowed."
                    )
                )


            # =================================================
            # UNIQUE FILE NAME
            # =================================================

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


            # =================================================
            # SAVE ORIGINAL
            # =================================================

            file.seek(0)

            file.save(
                original_path
            )


            saved_original_files.append(
                original_path
            )


            if not os.path.exists(
                original_path
            ):

                raise Exception(
                    "Original image could not be saved."
                )


            original_size_bytes = os.path.getsize(
                original_path
            )


            if original_size_bytes <= 0:

                raise Exception(
                    "Original image was saved as "
                    "an empty file."
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
            # OPEN IMAGE SAFELY
            # =================================================

            image = None

            resized_image = None


            try:

                image = Image.open(
                    original_path
                )


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
                    image.mode
                )

                print(
                    "IMAGE FORMAT:",
                    image.format
                )


                # =============================================
                # CHECK PIXEL COUNT BEFORE LOAD
                # =============================================

                validate_image_dimensions(
                    image,
                    width,
                    height
                )


                # =============================================
                # JPEG DRAFT
                # =============================================

                if image.format == "JPEG":

                    try:

                        image.draft(
                            image.mode,
                            (
                                width,
                                height
                            )
                        )

                        print(
                            "JPEG DRAFT MODE APPLIED"
                        )

                    except Exception as draft_error:

                        print(
                            "JPEG DRAFT ERROR:",
                            repr(draft_error)
                        )


                # =============================================
                # LOAD IMAGE
                # =============================================

                image.load()


                print(
                    "IMAGE LOADED SUCCESSFULLY"
                )


                # =============================================
                # CONVERT IMAGE MODE
                # =============================================

                if image.mode in (
                    "RGBA",
                    "LA",
                    "P"
                ):

                    image = image.convert(
                        "RGBA"
                    )

                else:

                    image = image.convert(
                        "RGB"
                    )


                # =============================================
                # RESIZE
                # =============================================

                resized_image = image.resize(
                    (
                        width,
                        height
                    ),
                    Image.Resampling.BILINEAR
                )


                # =============================================
                # JPEG
                # =============================================

                if output_format == "JPEG":

                    output_name = (
                        unique_name
                        + "_processed.jpg"
                    )


                    output_path = os.path.join(
                        batch_folder,
                        output_name
                    )


                    # JPEG does not support transparency.

                    if resized_image.mode != "RGB":

                        background = Image.new(
                            "RGB",
                            resized_image.size,
                            "white"
                        )


                        if (
                            "A"
                            in
                            resized_image.getbands()
                        ):

                            background.paste(
                                resized_image,
                                mask=(
                                    resized_image
                                    .getchannel("A")
                                )
                            )

                        else:

                            background.paste(
                                resized_image
                            )


                        resized_image.close()

                        resized_image = background


                    resized_image.save(
                        output_path,
                        "JPEG",
                        quality=quality,
                        optimize=False
                    )


                # =============================================
                # PNG
                # =============================================

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

                        converted = resized_image.convert(
                            "RGBA"
                        )

                        resized_image.close()

                        resized_image = converted


                    resized_image.save(
                        output_path,
                        "PNG",
                        optimize=False
                    )


                # =============================================
                # WEBP
                # =============================================

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

                        converted = resized_image.convert(
                            "RGB"
                        )

                        resized_image.close()

                        resized_image = converted


                    resized_image.save(
                        output_path,
                        "WEBP",
                        quality=quality,
                        method=4
                    )


                # =============================================
                # VERIFY OUTPUT
                # =============================================

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
                        "Processed image was created "
                        "as an empty file."
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
                            original_size_bytes
                            / 1024,
                            2
                        ),

                    "processed_size":
                        round(
                            processed_size
                            / 1024,
                            2
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


            except (
                Image.DecompressionBombError,
                Image.DecompressionBombWarning
            ) as bomb_error:

                print(
                    "IMAGE TOO LARGE:",
                    repr(bomb_error)
                )

                if image is not None:

                    try:
                        image.close()
                    except Exception:
                        pass

                if resized_image is not None:

                    try:
                        resized_image.close()
                    except Exception:
                        pass

                cleanup_folder(
                    batch_folder
                )

                for path in saved_original_files:

                    cleanup_file(
                        path
                    )

                return render_template(
                    "index.html",
                    error=(
                        "This image is too large to process "
                        "safely. Please use an image with "
                        "fewer than "
                        f"{MAX_IMAGE_PIXELS:,} pixels."
                    )
                )


            except ValueError as value_error:

                print(
                    "IMAGE VALIDATION ERROR:",
                    repr(value_error)
                )

                if image is not None:

                    try:
                        image.close()
                    except Exception:
                        pass

                if resized_image is not None:

                    try:
                        resized_image.close()
                    except Exception:
                        pass

                cleanup_folder(
                    batch_folder
                )

                for path in saved_original_files:

                    cleanup_file(
                        path
                    )

                return render_template(
                    "index.html",
                    error=str(
                        value_error
                    )
                )


            except Exception as image_error:

                print(
                    "IMAGE PROCESSING ERROR:",
                    repr(image_error)
                )

                if image is not None:

                    try:
                        image.close()
                    except Exception:
                        pass

                if resized_image is not None:

                    try:
                        resized_image.close()
                    except Exception:
                        pass

                continue


            finally:

                # =============================================
                # RELEASE MEMORY AFTER EVERY IMAGE
                # =============================================

                if image is not None:

                    try:
                        image.close()
                    except Exception:
                        pass


                if resized_image is not None:

                    try:
                        resized_image.close()
                    except Exception:
                        pass


                image = None

                resized_image = None


                # Force Python garbage collection.
                #
                # Important when multiple large images
                # are uploaded in one request.

                gc.collect()


        # ====================================================
        # NO SUCCESSFUL IMAGES
        # ====================================================

        if not processed_files:

            cleanup_folder(
                batch_folder
            )

            for path in saved_original_files:

                cleanup_file(
                    path
                )

            return render_template(
                "index.html",
                error=(
                    "No valid images were found. "
                    "Please select valid image files."
                )
            )


        # ====================================================
        # CALCULATE SAVED PERCENT
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
                *
                100,
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
            os.path.getsize(
                zip_path
            ),
            "BYTES"
        )


        # ====================================================
        # FINAL MEMORY CLEANUP
        # ====================================================

        gc.collect()


        # ====================================================
        # RETURN RESULT
        # ====================================================

        return render_template(

            "index.html",

            success=True,

            comparison_data=
                comparison_data,

            file_count=
                len(
                    processed_files
                ),

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
                    total_original_size
                    /
                    1024,
                    2
                ),

            compressed_size=
                round(
                    total_processed_size
                    /
                    1024,
                    2
                ),

            saved_percent=
                saved_percent,

            zip_name=
                zip_name,

            batch_id=
                batch_id
        )


    # ========================================================
    # REQUEST TOO LARGE
    # ========================================================

    except Exception as e:

        print(
            "GENERAL PROCESSING ERROR:",
            repr(e)
        )


        cleanup_folder(
            batch_folder
        )


        for path in saved_original_files:

            cleanup_file(
                path
            )


        gc.collect()


        return render_template(
            "index.html",
            error=(
                "Unable to process the images. "
                "Please check your files and try again."
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
# FILE TOO LARGE ERROR
# ============================================================

@app.errorhandler(413)
def request_entity_too_large(error):

    return render_template(
        "index.html",
        error=(
            "The uploaded file is too large. "
            "Please upload an image smaller than 30 MB."
        )
    ), 413


# ============================================================
# SERVER START
# ============================================================

if __name__ == "__main__":

    # Open browser only when running locally.
    # Render/Gunicorn will not execute this block.

    webbrowser.open(
        "http://127.0.0.1:5000"
    )


    app.run(
        debug=True,
        use_reloader=False
    )