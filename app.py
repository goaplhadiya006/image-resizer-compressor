import os
import uuid
import zipfile
import shutil
import webbrowser
import mimetypes
import gc

from flask import Flask, render_template, request, send_file
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
# MEMORY / UPLOAD PROTECTION
# ============================================================

# Maximum complete HTTP request size.
# 100 MB is enough for multiple normal images while preventing
# extremely large uploads from consuming server resources.

app.config["MAX_CONTENT_LENGTH"] = (
    100 * 1024 * 1024
)


# Maximum number of images in one request.

MAX_FILES = 20


# Maximum pixels allowed in a single image.
#
# 25 million pixels is approximately:
#
# 5000 x 5000
#
# This protects Render RAM from extremely high-resolution images.

MAX_IMAGE_PIXELS_ALLOWED = 25_000_000


# Pillow decompression bomb protection.

Image.MAX_IMAGE_PIXELS = (
    MAX_IMAGE_PIXELS_ALLOWED
)


# ============================================================
# CREATE FOLDERS
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
# ALLOWED FILES
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
# HOME
# ============================================================

@app.route("/")
def home():

    return render_template(
        "index.html"
    )


# ============================================================
# IMAGE RESIZE + COMPRESS
# ============================================================

@app.route(
    "/resize",
    methods=["POST"]
)
def resize_image():

    files = request.files.getlist(
        "image"
    )


    # Remove empty file entries.

    files = [
        file
        for file in files
        if file and file.filename
    ]


    # No images.

    if not files:

        return render_template(
            "index.html",
            error="Please select at least one image."
        )


    # Maximum file count.

    if len(files) > MAX_FILES:

        return render_template(
            "index.html",
            error=f"You can process maximum {MAX_FILES} images at a time."
        )


    # ========================================================
    # GET SETTINGS
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
    # VALIDATE SETTINGS
    # ========================================================

    try:

        width = int(width)

        height = int(height)

        quality = int(quality)

    except (
        ValueError,
        TypeError
    ):

        return render_template(
            "index.html",
            error="Please enter valid width, height and quality values."
        )


    if width <= 0 or height <= 0:

        return render_template(
            "index.html",
            error="Width and height must be greater than 0."
        )


    # Protect server from creating extremely huge
    # output images.

    if width > 10000 or height > 10000:

        return render_template(
            "index.html",
            error="Maximum output dimensions are 10000 × 10000 pixels."
        )


    if quality < 10 or quality > 100:

        return render_template(
            "index.html",
            error="Compression quality must be between 10 and 100."
        )


    if output_format not in ALLOWED_FORMATS:

        return render_template(
            "index.html",
            error="Please select a valid output format."
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


    processed_files = []

    comparison_data = []

    total_original_size = 0

    total_processed_size = 0


    # ========================================================
    # PROCESS IMAGES ONE BY ONE
    # ========================================================

    try:

        for index, file in enumerate(files):

            image = None

            resized_image = None


            # ------------------------------------------------
            # SECURE FILE NAME
            # ------------------------------------------------

            original_filename = secure_filename(
                file.filename
            )


            if not original_filename:

                continue


            # ------------------------------------------------
            # CHECK EXTENSION
            # ------------------------------------------------

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


            if input_extension not in ALLOWED_EXTENSIONS:

                shutil.rmtree(
                    batch_folder,
                    ignore_errors=True
                )

                return render_template(
                    "index.html",
                    error=(
                        "Only JPG, JPEG, PNG and WEBP "
                        "images are allowed."
                    )
                )


            # ------------------------------------------------
            # UNIQUE NAME
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
            # SAVE ORIGINAL TO DISK
            # ------------------------------------------------

            file.seek(0)

            file.save(
                original_path
            )


            if not os.path.isfile(
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
                    "Original image was saved as an empty file."
                )


            total_original_size += (
                original_size_bytes
            )


            print(
                "ORIGINAL FILE:",
                original_path,
                "SIZE:",
                original_size_bytes,
                "BYTES"
            )


            # ------------------------------------------------
            # OPEN IMAGE
            #
            # IMPORTANT:
            # We first inspect image metadata before loading
            # the complete image into RAM.
            # ------------------------------------------------

            try:

                image = Image.open(
                    original_path
                )


                print(
                    "IMAGE OPENED:",
                    original_filename,
                    "SIZE:",
                    image.size,
                    "MODE:",
                    image.mode,
                    "FORMAT:",
                    image.format
                )


            except (
                UnidentifiedImageError,
                OSError,
                ValueError
            ) as image_error:

                print(
                    "IMAGE OPEN ERROR:",
                    repr(image_error)
                )

                continue


            # ------------------------------------------------
            # VERIFY REAL IMAGE FORMAT
            # ------------------------------------------------

            if image.format not in ALLOWED_FORMATS:

                image.close()

                image = None

                continue


            # ------------------------------------------------
            # CHECK IMAGE PIXELS BEFORE DECODING
            #
            # This is one of the most important memory fixes.
            # ------------------------------------------------

            image_width = image.width

            image_height = image.height

            image_pixels = (
                image_width
                * image_height
            )


            print(
                "IMAGE PIXELS:",
                image_pixels
            )


            if image_pixels > MAX_IMAGE_PIXELS_ALLOWED:

                print(
                    "IMAGE TOO LARGE:",
                    image_pixels,
                    "pixels"
                )

                image.close()

                image = None

                continue


            # ------------------------------------------------
            # JPEG MEMORY OPTIMIZATION
            # ------------------------------------------------

            if image.format == "JPEG":

                try:

                    image.draft(
                        "RGB",
                        (
                            width,
                            height
                        )
                    )

                except Exception as draft_error:

                    print(
                        "JPEG DRAFT WARNING:",
                        repr(draft_error)
                    )


            # ------------------------------------------------
            # LOAD IMAGE
            # ------------------------------------------------

            try:

                image.load()

            except Exception as image_load_error:

                print(
                    "IMAGE LOAD ERROR:",
                    repr(image_load_error)
                )

                image.close()

                image = None

                continue


            # ------------------------------------------------
            # CONVERT IMAGE MODE
            # ------------------------------------------------

            try:

                if image.mode in (
                    "RGBA",
                    "LA",
                    "P"
                ):

                    converted_image = image.convert(
                        "RGBA"
                    )

                else:

                    converted_image = image.convert(
                        "RGB"
                    )


                # Close original decoded image
                # before continuing.

                image.close()

                image = None


                image = converted_image

                converted_image = None


            except Exception as convert_error:

                print(
                    "IMAGE CONVERSION ERROR:",
                    repr(convert_error)
                )

                if image is not None:

                    image.close()

                    image = None

                continue


            # ------------------------------------------------
            # RESIZE
            # ------------------------------------------------

            try:

                resized_image = image.resize(
                    (
                        width,
                        height
                    ),
                    Image.Resampling.BILINEAR
                )

            except Exception as resize_error:

                print(
                    "IMAGE RESIZE ERROR:",
                    repr(resize_error)
                )

                image.close()

                image = None

                continue


            # ------------------------------------------------
            # JPEG
            # ------------------------------------------------

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


                    if "A" in resized_image.getbands():

                        background.paste(
                            resized_image,
                            mask=resized_image.getchannel(
                                "A"
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


            # ------------------------------------------------
            # PNG
            # ------------------------------------------------

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


            # ------------------------------------------------
            # WEBP
            # ------------------------------------------------

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


            # ------------------------------------------------
            # CHECK PROCESSED FILE
            # ------------------------------------------------

            if not os.path.isfile(
                output_path
            ):

                raise Exception(
                    "Processed image was not created."
                )


            processed_size = (
                os.path.getsize(
                    output_path
                )
            )


            if processed_size <= 0:

                raise Exception(
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
                output_path,
                "SIZE:",
                processed_size,
                "BYTES"
            )


            # ------------------------------------------------
            # IMPORTANT MEMORY CLEANUP
            # ------------------------------------------------

            if resized_image is not None:

                resized_image.close()

                resized_image = None


            if image is not None:

                image.close()

                image = None


            # Remove references and force garbage collection.

            gc.collect()


            print(
                "MEMORY CLEANUP COMPLETE FOR:",
                original_filename
            )


        # ====================================================
        # CHECK RESULTS
        # ====================================================

        if not processed_files:

            shutil.rmtree(
                batch_folder,
                ignore_errors=True
            )

            return render_template(
                "index.html",
                error=(
                    "No valid images were processed. "
                    "The image may be unsupported, corrupt, "
                    "or too large. Maximum supported resolution "
                    "is 25 million pixels."
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


                zip_file.write(
                    file_path,
                    filename
                )


        print(
            "ZIP CREATED:",
            zip_path,
            "SIZE:",
            os.path.getsize(
                zip_path
            )
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
            "IMAGE PROCESSING ERROR:",
            repr(e)
        )


        # Close any image still open.

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


        gc.collect()


        shutil.rmtree(
            batch_folder,
            ignore_errors=True
        )


        return render_template(
            "index.html",
            error=(
                "Unable to process the images. "
                "Please try a smaller image or fewer images."
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


    if not os.path.isfile(
        file_path
    ):

        return (
            "Download file not found.",
            404
        )


    return send_file(
        file_path,
        as_attachment=True,
        conditional=False,
        etag=False,
        max_age=0
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
        os.path.getsize(file_path)
        if os.path.exists(file_path)
        else 0
    )


    if not os.path.isfile(
        file_path
    ):

        return (
            "Original image not found.",
            404
        )


    mime_type = (
        mimetypes.guess_type(
            file_path
        )[0]
        or "application/octet-stream"
    )


    return send_file(
        file_path,
        mimetype=mime_type,
        conditional=False,
        etag=False,
        max_age=0
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
        os.path.getsize(file_path)
        if os.path.exists(file_path)
        else 0
    )


    if not os.path.isfile(
        file_path
    ):

        return (
            "Processed image not found.",
            404
        )


    mime_type = (
        mimetypes.guess_type(
            file_path
        )[0]
        or "application/octet-stream"
    )


    return send_file(
        file_path,
        mimetype=mime_type,
        conditional=False,
        etag=False,
        max_age=0
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
        os.path.getsize(file_path)
        if os.path.exists(file_path)
        else 0
    )


    if not os.path.isfile(
        file_path
    ):

        return (
            "Processed image not found.",
            404
        )


    mime_type = (
        mimetypes.guess_type(
            file_path
        )[0]
        or "application/octet-stream"
    )


    return send_file(
        file_path,
        mimetype=mime_type,
        as_attachment=True,
        conditional=False,
        etag=False,
        max_age=0
    )


# ============================================================
# RUN APP
# ============================================================

if __name__ == "__main__":

    webbrowser.open(
        "http://127.0.0.1:5000"
    )

    app.run(
        debug=True,
        use_reloader=False
    )