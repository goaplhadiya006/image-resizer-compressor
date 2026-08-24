import os
import uuid
import zipfile
import shutil
import webbrowser
import mimetypes

from flask import Flask, render_template, request, send_from_directory, send_file
from PIL import Image
from werkzeug.utils import secure_filename


app = Flask(__name__)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
PROCESSED_FOLDER = os.path.join(BASE_DIR, "processed")

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["PROCESSED_FOLDER"] = PROCESSED_FOLDER


# NO 10 MB LIMIT
# app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024


os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)


# Allow large images
Image.MAX_IMAGE_PIXELS = None


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


@app.route("/")
def home():

    return render_template(
        "index.html"
    )


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

        return render_template(
            "index.html",
            error="Please select at least one image."
        )


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


    try:

        for index, file in enumerate(files):

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


            if input_extension not in ALLOWED_EXTENSIONS:

                shutil.rmtree(
                    batch_folder,
                    ignore_errors=True
                )

                return render_template(
                    "index.html",
                    error="Only JPG, JPEG, PNG and WEBP images are allowed."
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


            # SAVE ORIGINAL DIRECTLY
            # Avoid reading the complete large image into RAM

            file.seek(0)

            file.save(
                original_path
            )


            if not os.path.exists(original_path):

                raise Exception(
                    "Original image could not be saved."
                )


            original_size_bytes = os.path.getsize(
                original_path
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


            # OPEN IMAGE FROM DISK

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
                    image.mode
                )


                # Faster JPEG decoding when resizing
                # a very large image to a smaller size

                if image.format == "JPEG":

                    try:

                        image.draft(
                            image.mode,
                            (
                                width,
                                height
                            )
                        )

                    except Exception:

                        pass


                image.load()


            except Exception as image_error:

                print(
                    "IMAGE OPEN ERROR:",
                    repr(image_error)
                )

                continue


            # CONVERT IMAGE MODE

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


            # RESIZE IMAGE
            # BILINEAR is faster than LANCZOS

            resized_image = image.resize(
                (
                    width,
                    height
                ),
                Image.Resampling.BILINEAR
            )


            # JPEG

            if output_format == "JPEG":

                output_name = (
                    unique_name
                    + "_processed.jpg"
                )


                output_path = os.path.join(
                    batch_folder,
                    output_name
                )


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


                    resized_image = background


                resized_image.save(
                    output_path,
                    "JPEG",
                    quality=quality,
                    optimize=False
                )


            # PNG

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

                    resized_image = resized_image.convert(
                        "RGBA"
                    )


                resized_image.save(
                    output_path,
                    "PNG",
                    optimize=False
                )


            # WEBP

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

                    resized_image = resized_image.convert(
                        "RGB"
                    )


                resized_image.save(
                    output_path,
                    "WEBP",
                    quality=quality,
                    method=4
                )


            # CHECK PROCESSED FILE

            if not os.path.exists(output_path):

                raise Exception(
                    "Processed image was not created."
                )


            processed_size = os.path.getsize(
                output_path
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


            # RELEASE MEMORY AFTER EACH IMAGE

            image.close()

            resized_image.close()


        if not processed_files:

            shutil.rmtree(
                batch_folder,
                ignore_errors=True
            )

            return render_template(
                "index.html",
                error="No valid images were found. Please select valid image files."
            )


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


        # CREATE ZIP

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
            os.path.getsize(zip_path)
        )


        return render_template(

            "index.html",

            success=True,

            comparison_data=
                comparison_data,

            file_count=
                len(processed_files),

            width=width,

            height=height,

            quality=quality,

            format=output_format,

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


        shutil.rmtree(
            batch_folder,
            ignore_errors=True
        )


        return render_template(
            "index.html",
            error="Unable to process the images. Please check your files and try again."
        ), 500


# DOWNLOAD ZIP

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


    if not os.path.isfile(file_path):

        return render_template(
            "index.html",
            error="Download file not found."
        ), 404


    return send_file(
        file_path,
        as_attachment=True,
        conditional=False,
        etag=False,
        max_age=0
    )


# ORIGINAL IMAGE
# Changed only image serving method for better
# mobile/browser compatibility.

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


    if not os.path.isfile(file_path):

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


# PROCESSED IMAGE
# Changed only image serving method for better
# mobile/browser compatibility.

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


    if not os.path.isfile(file_path):

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


# DOWNLOAD INDIVIDUAL IMAGE

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


    if not os.path.isfile(file_path):

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


if __name__ == "__main__":

    webbrowser.open(
        "http://127.0.0.1:5000"
    )

    app.run(
        debug=True,
        use_reloader=False
    )