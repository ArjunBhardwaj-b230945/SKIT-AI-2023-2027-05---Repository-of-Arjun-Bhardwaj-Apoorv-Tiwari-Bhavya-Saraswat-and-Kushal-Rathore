require("dotenv").config();

const express = require("express");

const authRoutes = require("./routes/auth");
const protectedRoutes = require("./routes/protected");

const app = express();


// ======================================================
// Middleware
// ======================================================

app.use(express.json());


// ======================================================
// Health Check
// ======================================================

app.get("/", (req, res) => {
    res.status(200).json({
        success: true,
        message: "Authentication API is running"
    });
});


// ======================================================
// Routes
// ======================================================

app.use("/auth", authRoutes);

app.use("/api", protectedRoutes);


// ======================================================
// 404 Handler
// ======================================================

app.use((req, res) => {
    res.status(404).json({
        success: false,
        message: "Route not found"
    });
});


// ======================================================
// Global Error Handler
// ======================================================

app.use((err, req, res, next) => {

    console.error(err.stack);

    res.status(500).json({
        success: false,
        message: "Internal server error"
    });

});


// ======================================================
// Server
// ======================================================

const PORT = process.env.PORT || 3000;

app.listen(PORT, () => {
    console.log(`Server running on http://localhost:${PORT}`);
});