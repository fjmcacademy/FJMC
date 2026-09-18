// firebase.js

import {
    initializeApp
} from "https://www.gstatic.com/firebasejs/12.1.0/firebase-app.js";

import {
    getAuth
} from "https://www.gstatic.com/firebasejs/12.1.0/firebase-auth.js";

import {
    getFirestore
} from "https://www.gstatic.com/firebasejs/12.1.0/firebase-firestore.js";


const firebaseConfig = {

    apiKey: "AIzaSyCpT81NWAqryCFQ5IALv6nd35K1WBaji3c",

    authDomain: "fjmc-academy-5c2dc.firebaseapp.com",

    projectId: "fjmc-academy-5c2dc",

    storageBucket: "fjmc-academy-5c2dc.firebasestorage.app",

    messagingSenderId: "576982683668",

    appId: "1:576982683668:web:eecabe69a82983efb51701",

    measurementId: "G-44NMV4D4QN"
};


const app = initializeApp(firebaseConfig);


export const auth = getAuth(app);

export const db = getFirestore(app);