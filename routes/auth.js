const express = require("express");

const { Signin, Signup } = require("../controllers/auth");

const router = express.Router();

router.post("/signin", Signin);
router.post("/signup", Signup);

module.exports = router;