const jwt = require("jsonwebtoken");
const bcrypt = require("bcryptjs");

const users = [];

const JWT_SECRET = process.env.JWT_SECRET || "my_super_secret_key";
const JWT_EXPIRES_IN = process.env.JWT_EXPIRES_IN || "1h";


// ======================================================
// Generate JWT Token
// ======================================================

function generateToken(user) {
    return jwt.sign(
        {
            id: user.id,
            email: user.email,
            role: user.role
        },
        JWT_SECRET,
        {
            expiresIn: JWT_EXPIRES_IN
        }
    );
}


// ======================================================
// SIGNUP
// ======================================================

async function Signup(req, res) {
    try {
        const { email, password, role } = req.body;

        // Validate required fields
        if (!email || !password) {
            return res.status(400).json({
                success: false,
                message: "Email and password are required"
            });
        }

        // Normalize email
        const normalizedEmail = email.trim().toLowerCase();

        // Basic email validation
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

        if (!emailRegex.test(normalizedEmail)) {
            return res.status(400).json({
                success: false,
                message: "Please provide a valid email address"
            });
        }

        // Password validation
        if (password.length < 6) {
            return res.status(400).json({
                success: false,
                message: "Password must contain at least 6 characters"
            });
        }

        // Check duplicate user
        const existingUser = users.find(
            user => user.email === normalizedEmail
        );

        if (existingUser) {
            return res.status(409).json({
                success: false,
                message: "User already exists"
            });
        }

        // Only allow valid roles
        const userRole = role === "admin" ? "admin" : "user";

        // Hash password
        const hashedPassword = await bcrypt.hash(password, 10);

        // Create user
        const user = {
            id: users.length + 1,
            email: normalizedEmail,
            password: hashedPassword,
            role: userRole,
            createdAt: new Date()
        };

        users.push(user);

        // Generate JWT
        const token = generateToken(user);

        return res.status(201).json({
            success: true,
            message: "Signup successful",
            token,
            user: {
                id: user.id,
                email: user.email,
                role: user.role
            }
        });

    } catch (error) {
        console.error("Signup error:", error);

        return res.status(500).json({
            success: false,
            message: "Internal server error"
        });
    }
}


// ======================================================
// SIGNIN
// ======================================================

async function Signin(req, res) {
    try {
        const { email, password } = req.body;

        // Validate input
        if (!email || !password) {
            return res.status(400).json({
                success: false,
                message: "Email and password are required"
            });
        }

        // Normalize email
        const normalizedEmail = email.trim().toLowerCase();

        // Find user
        const user = users.find(
            user => user.email === normalizedEmail
        );

        // Don't reveal whether email exists
        if (!user) {
            return res.status(401).json({
                success: false,
                message: "Invalid email or password"
            });
        }

        // Compare password with hashed password
        const passwordMatch = await bcrypt.compare(
            password,
            user.password
        );

        if (!passwordMatch) {
            return res.status(401).json({
                success: false,
                message: "Invalid email or password"
            });
        }

        // Generate new JWT
        const token = generateToken(user);

        return res.status(200).json({
            success: true,
            message: "Signin successful",
            token,
            user: {
                id: user.id,
                email: user.email,
                role: user.role
            }
        });

    } catch (error) {
        console.error("Signin error:", error);

        return res.status(500).json({
            success: false,
            message: "Internal server error"
        });
    }
}


// ======================================================
// EXPORT
// ======================================================

module.exports = {
    Signup,
    Signin
};