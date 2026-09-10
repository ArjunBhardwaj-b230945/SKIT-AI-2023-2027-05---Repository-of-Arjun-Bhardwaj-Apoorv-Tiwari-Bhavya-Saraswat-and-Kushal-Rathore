const express = require("express");

const {
    authenticateToken,
    authorizeRole
} = require("../middleware/authMiddleware");

const router = express.Router();


// ======================================================
// Protected user route
// ======================================================

router.get("/profile", authenticateToken, (req, res) => {

    return res.status(200).json({
        success: true,
        message: "Protected profile accessed successfully",
        user: req.user
    });

});


// ======================================================
// Protected dashboard
// Any authenticated user can access
// ======================================================

router.get("/dashboard", authenticateToken, (req, res) => {

    return res.status(200).json({
        success: true,
        message: "Welcome to the protected dashboard",
        user: req.user
    });

});


// ======================================================
// Admin-only route
// ======================================================

router.get(
    "/admin",
    authenticateToken,
    authorizeRole("admin"),
    (req, res) => {

        return res.status(200).json({
            success: true,
            message: "Admin resource accessed successfully",
            user: req.user
        });

    }
);


module.exports = router;