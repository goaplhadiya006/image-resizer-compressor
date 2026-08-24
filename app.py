import os
import uuid
import zipfile
import shutil
import webbrowser

from flask import Flask, render_template, request, send_from_directory
from PIL import Image
from werkzeug.utils import secure_filename


app = Flask(__name__)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
PROCESSED_FOLDER = os.path.join(BASE_DIR, "processed")

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["PROCESSED_FOLDER"] = PROCESSED_FOLDER

app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024


os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)


# Prevent extremely large images from consuming too much memory
Image.MAX_IMAGE_PIXELS = 25_000_000


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


# FILE SIZE ERROR

@app.errorhandler(413)
def file_too_large(error):

    return render_template(
        "index.html",
        error="File size is too large. Maximum allowed size is 10 MB."
    ), 413


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


    # Prevent extremely large output dimensions
    if width * height > 25_000_000:

        return render_template(
            "index.html",
            error="Output dimensions are too large. Please use smaller dimensions."
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


            # OPEN IMAGE

            try:

                file.seek(0)

                image = Image.open(file)

                image.load()

                print(
                    "IMAGE OPENED:",
                    original_filename,
                    "SIZE:",
                    image.size,
                    "MODE:",
                    image.mode
                )

            except Exception as image_error:

                print(
                    "IMAGE OPEN ERROR:",
                    repr(image_error)
                )

                continue


            file.seek(0)

            original_data = file.read()


            original_size_bytes = len(
                original_data
            )


            # CHECK ORIGINAL FILE SIZE

            if original_size_bytes <= 0:

                print(
                    "EMPTY ORIGINAL FILE:",
                    original_filename
                )

                continue


            total_original_size += (
                original_size_bytes
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


            with open(
                original_path,
                "wb"
            ) as original_file:

                original_file.write(
                    original_data
                )


            # CHECK ORIGINAL FILE AFTER SAVE

            if not os.path.exists(original_path):

                raise Exception(
                    "Original image could not be saved."
                )


            original_saved_size = os.path.getsize(
                original_path
            )


            print(
                "ORIGINAL FILE SAVED:",
                original_path,
                "SIZE:",
                original_saved_size,
                "BYTES"
            )


            if original_saved_size <= 0:

                raise Exception(
                    "Original image was saved as an empty file."
                )


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

            resized_image = image.resize(
                (
                    width,
                    height
                ),
                Image.Resampling.LANCZOS
            )


            # JPEG

            if output_format == "JPEG":

                output_extension = "jpg"


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


                output_name = (
                    unique_name
                    + "_processed.jpg"
                )


                output_path = os.path.join(
                    batch_folder,
                    output_name
                )


                resized_image.save(
                    output_path,
                    "JPEG",
                    quality=quality,
                    optimize=True
                )


            # PNG

            elif output_format == "PNG":

                output_extension = "png"


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
                    optimize=True
                )


            # WEBP

            else:

                output_extension = "webp"


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
                    method=6
                )


            # CHECK PROCESSED FILE

            if not os.path.exists(output_path):

                raise Exception(
                    "Processed image was not created."
                )


            processed_size = os.path.getsize(
                output_path
            )


            print(
                "PROCESSED FILE SAVED:",
                output_path,
                "SIZE:",
                processed_size,
                "BYTES"
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


    # ERROR LOGGING

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


    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename
    )


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


    return send_from_directory(
        batch_folder,
        filename
    )


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


    return send_from_directory(
        batch_folder,
        filename,
        as_attachment=True
    )


if __name__ == "__main__":

    webbrowser.open(
        "http://127.0.0.1:5000"
    )

    app.run(
        debug=True,
        use_reloader=False
    )