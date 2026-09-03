const jwt = require("jsonwebtoken");

const users = [];

const JWT_SECRET = process.env.JWT_SECRET || "my_super_secret_key";

// ==================== SIGNUP ====================

function Signup(req, res) {
    const { email, password } = req.body;

    // Validate input
    if (!email || !password) {
        return res.status(400).json({
            success: false,
            message: "Email and password are required"
        });
    }

    // Check if user already exists
    const existingUser = users.find(user => user.email === email);

    if (existingUser) {
        return res.status(409).json({
            success: false,
            message: "User already exists"
        });
    }

    // Create new user
    const user = {
        id: users.length + 1,
        email,
        password
    };

    users.push(user);

    // Generate JWT
    const token = jwt.sign(
        {
            id: user.id,
            email: user.email
        },
        JWT_SECRET,
        {
            expiresIn: "1h"
        }
    );

    return res.status(201).json({
        success: true,
        message: "Signup successful",
        token
    });
}


// ==================== SIGNIN ====================

function Signin(req, res) {
    const { email, password } = req.body;

    // Validate input
    if (!email || !password) {
        return res.status(400).json({
            success: false,
            message: "Email and password are required"
        });
    }

    // Find user
    const user = users.find(user => user.email === email);

    if (!user) {
        return res.status(401).json({
            success: false,
            message: "Invalid email or password"
        });
    }

    // Check password
    if (user.password !== password) {
        return res.status(401).json({
            success: false,
            message: "Invalid email or password"
        });
    }

    // Generate JWT
    const token = jwt.sign(
        {
            id: user.id,
            email: user.email
        },
        JWT_SECRET,
        {
            expiresIn: "1h"
        }
    );

    return res.status(200).json({
        success: true,
        message: "Signin successful",
        token
    });
}


module.exports = {
    Signup,
    Signin
};