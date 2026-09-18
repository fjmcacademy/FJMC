console.log("LOGIN JS LOADED");
import { auth } from "./firebase.js";

import {
    signInWithEmailAndPassword
} from "https://www.gstatic.com/firebasejs/12.1.0/firebase-auth.js";

const loginForm = document.getElementById("loginForm");
const message = document.getElementById("loginMessage");

loginForm.addEventListener("submit", async function (event) {

    event.preventDefault();

    const email = document.getElementById("email").value.trim();
    const password = document.getElementById("password").value;

    message.textContent = "Checking...";

    try {

        await signInWithEmailAndPassword(
            auth,
            email,
            password
        );

        message.textContent = "Login successful!";

        window.location.href = "dashboard.html";

    } catch (error) {

        console.error(error);

        message.textContent =
            "Error: " + error.code;

    }

});