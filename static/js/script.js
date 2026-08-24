const imageInput =
    document.getElementById("imageInput");

const dropZone =
    document.getElementById("dropZone");

const previewBox =
    document.getElementById("previewBox");

const previewImage =
    document.getElementById("previewImage");

const fileName =
    document.getElementById("fileName");

const originalSize =
    document.getElementById("originalSize");

const removeImage =
    document.getElementById("removeImage");

const clearAll =
    document.getElementById("clearAll");

const widthInput =
    document.getElementById("width");

const heightInput =
    document.getElementById("height");

const aspectRatioCheckbox =
    document.getElementById("aspectRatio");

const qualitySlider =
    document.getElementById("quality");

const qualityValue =
    document.getElementById("qualityValue");

const formatInput =
    document.getElementById("format");

const form =
    document.querySelector("form");

const processButton =
    document.querySelector(".process-btn");

const themeToggle =
    document.getElementById("themeToggle");


let aspectRatio = 1;

let previewUrl = null;

// DARK / LIGHT MODE

function setTheme(theme) {

    if (theme === "dark") {

        document.body.classList.add(
            "dark-mode"
        );

        themeToggle.innerText =
            "☀️ Light Mode";

    } else {

        document.body.classList.remove(
            "dark-mode"
        );

        themeToggle.innerText =
            "🌙 Dark Mode";
    }


    localStorage.setItem(
        "imageToolTheme",
        theme
    );
}


/* LOAD SAVED THEME */

const savedTheme =
    localStorage.getItem(
        "imageToolTheme"
    );


if (savedTheme === "dark") {

    setTheme("dark");

} else {

    setTheme("light");
}


/* THEME BUTTON */

themeToggle.addEventListener(
    "click",
    function () {

        const isDark =
            document.body.classList.contains(
                "dark-mode"
            );


        if (isDark) {

            setTheme("light");

        } else {

            setTheme("dark");
        }
    }
);

// IMAGE SELECT

imageInput.addEventListener(
    "change",
    function () {

        if (this.files.length === 0) {
            return;
        }

        showImages(this.files);
    }
);

// CLICK DROP ZONE

dropZone.addEventListener(
    "click",
    function (event) {

        if (
            event.target.tagName === "LABEL" ||
            event.target.tagName === "INPUT" ||
            event.target.closest("label")
        ) {
            return;
        }

        imageInput.click();
    }
);


// DRAG OVER

dropZone.addEventListener(
    "dragover",
    function (event) {

        event.preventDefault();

        dropZone.classList.add(
            "dragover"
        );
    }
);

// DRAG LEAVE

dropZone.addEventListener(
    "dragleave",
    function () {

        dropZone.classList.remove(
            "dragover"
        );
    }
);

//   DROP

dropZone.addEventListener(
    "drop",
    function (event) {

        event.preventDefault();

        dropZone.classList.remove(
            "dragover"
        );

        const files =
            event.dataTransfer.files;


        if (
            !files ||
            files.length === 0
        ) {
            return;
        }


        for (
            let i = 0;
            i < files.length;
            i++
        ) {

            if (
                !files[i].type.startsWith(
                    "image/"
                )
            ) {

                showError(
                    "Please select image files only."
                );

                return;
            }
        }


        const dataTransfer =
            new DataTransfer();


        for (
            let i = 0;
            i < files.length;
            i++
        ) {

            dataTransfer.items.add(
                files[i]
            );
        }


        imageInput.files =
            dataTransfer.files;


        showImages(
            imageInput.files
        );
    }
);

// SHOW IMAGES

function showImages(files) {

    if (previewUrl) {

        URL.revokeObjectURL(
            previewUrl
        );
    }


    const firstFile =
        files[0];


    previewUrl =
        URL.createObjectURL(
            firstFile
        );


    previewImage.src =
        previewUrl;


    previewBox.style.display =
        "block";


    fileName.innerText =
        files.length +
        " image" +
        (
            files.length > 1
                ? "s"
                : ""
        ) +
        " selected";


    let totalSize = 0;


    for (
        let i = 0;
        i < files.length;
        i++
    ) {

        totalSize +=
            files[i].size;
    }


    originalSize.innerText =
        "Total File Size: " +
        formatFileSize(
            totalSize
        );


    const image =
        new Image();


    image.onload =
        function () {

            aspectRatio =
                image.width /
                image.height;


            widthInput.value =
                image.width;


            heightInput.value =
                image.height;
        };


    image.src =
        previewUrl;
}

// FILE SIZE

function formatFileSize(bytes) {

    if (bytes < 1024) {

        return (
            bytes +
            " Bytes"
        );
    }


    if (
        bytes <
        1024 * 1024
    ) {

        return (
            (
                bytes / 1024
            ).toFixed(2) +
            " KB"
        );
    }


    return (
        (
            bytes /
            (1024 * 1024)
        ).toFixed(2) +
        " MB"
    );
}

//  WIDTH

widthInput.addEventListener(
    "input",
    function () {

        if (
            !aspectRatioCheckbox.checked
        ) {
            return;
        }


        const width =
            parseInt(
                this.value
            );


        if (
            isNaN(width) ||
            aspectRatio <= 0
        ) {
            return;
        }


        heightInput.value =
            Math.round(
                width /
                aspectRatio
            );
    }
);

// HEIGHT

heightInput.addEventListener(
    "input",
    function () {

        if (
            !aspectRatioCheckbox.checked
        ) {
            return;
        }


        const height =
            parseInt(
                this.value
            );


        if (
            isNaN(height) ||
            aspectRatio <= 0
        ) {
            return;
        }


        widthInput.value =
            Math.round(
                height *
                aspectRatio
            );
    }
);

//  QUALITY

qualitySlider.addEventListener(
    "input",
    function () {

        qualityValue.innerText =
            this.value + "%";
    }
);

// REMOVE IMAGE

removeImage.addEventListener(
    "click",
    function () {

        imageInput.value = "";

        previewImage.src = "";

        previewBox.style.display =
            "none";

        fileName.innerText = "";

        originalSize.innerText = "";

        widthInput.value = "";

        heightInput.value = "";


        if (previewUrl) {

            URL.revokeObjectURL(
                previewUrl
            );

            previewUrl = null;
        }
    }
);

// CLEAR ALL

clearAll.addEventListener(
    "click",
    function () {

        imageInput.value = "";

        previewImage.src = "";

        previewBox.style.display =
            "none";

        fileName.innerText = "";

        originalSize.innerText = "";

        widthInput.value = "";

        heightInput.value = "";

        aspectRatioCheckbox.checked =
            true;

        aspectRatio = 1;

        qualitySlider.value = 80;

        qualityValue.innerText =
            "80%";

        formatInput.value =
            "JPEG";


        if (previewUrl) {

            URL.revokeObjectURL(
                previewUrl
            );

            previewUrl = null;
        }


        processButton.disabled =
            false;

        processButton.innerText =
            "🚀 Resize & Compress Images";

        processButton.style.cursor =
            "pointer";


        const resultSection =
            document.getElementById(
                "resultSection"
            );


        if (resultSection) {
            resultSection.remove();
        }


        dropZone.scrollIntoView({
            behavior: "smooth",
            block: "center"
        });
    }
);

//    PROCESSING LOADER

form.addEventListener(
    "submit",
    function () {

        processButton.innerText =
            "⏳ Processing... Please wait";

        processButton.disabled =
            true;

        processButton.style.cursor =
            "not-allowed";
    }
);

// SHOW ERROR

function showError(message) {

    const oldError =
        document.getElementById(
            "errorMessage"
        );


    if (oldError) {
        oldError.remove();
    }


    const errorBox =
        document.createElement(
            "div"
        );


    errorBox.className =
        "error-message";


    errorBox.id =
        "errorMessage";


    errorBox.innerHTML = `
        <span class="error-icon">
            ⚠️
        </span>

        <div class="error-content">

            <strong>
                Something went wrong
            </strong>

            <p>
                ${message}
            </p>

        </div>

        <button type="button"
                id="closeError">
            ✕
        </button>
    `;


    const container =
        document.querySelector(
            ".container"
        );


    container.insertBefore(
        errorBox,
        container.firstChild
    );


    document
        .getElementById(
            "closeError"
        )
        .addEventListener(
            "click",
            function () {

                errorBox.remove();
            }
        );
}

//    CLOSE SERVER ERROR

const closeError =
    document.getElementById(
        "closeError"
    );


if (closeError) {

    closeError.addEventListener(
        "click",
        function () {

            const errorMessage =
                document.getElementById(
                    "errorMessage"
                );


            if (errorMessage) {

                errorMessage.remove();
            }
        }
    );
}

// INITIAL QUALITY

qualityValue.innerText =
    qualitySlider.value + "%";