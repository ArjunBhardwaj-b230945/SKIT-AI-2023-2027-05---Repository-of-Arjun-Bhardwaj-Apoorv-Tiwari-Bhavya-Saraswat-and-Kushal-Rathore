const express = require("express");

const router = require("./routes/auth");

const app = express();

app.use(express.json());

// Mount auth routes
app.use("/", router);

const PORT = process.env.PORT || 3000;

app.listen(PORT, () => {
    console.log(`Server running on http://localhost:${PORT}`);
});