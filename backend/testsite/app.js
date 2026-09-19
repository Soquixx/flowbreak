const loginForm = document.getElementById("loginForm");
const searchForm = document.getElementById("searchForm");
const profileButton = document.getElementById("profileButton");
const exportButton = document.getElementById("exportButton");
const crashButton = document.getElementById("crashButton");
const checkoutForm = document.getElementById("checkoutForm");

// FLOW 1: Login

loginForm.addEventListener("submit", (event) => {
    event.preventDefault();

    const email = document.getElementById("email").value;

    if (!email) {
        document.getElementById("loginStatus").textContent =
            "Please enter your email.";
        return;
    }

    loginState.user = email;
});

// FLOW 2: Search

searchForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const query = document.getElementById("searchInput").value;

    try {
        const response = await fetch(
            `/api/search?q=${encodeURIComponent(query)}`
        );

        if (!response.ok) {
            throw new Error(
                `Search API failed with status ${response.status}`
            );
        }

        const data = await response.json();

        document.getElementById("searchResults").textContent =
            JSON.stringify(data);
    } catch (error) {
        console.error("SEARCH_FLOW_FAILED:", error);

        document.getElementById("searchResults").textContent =
            "Unable to load search results.";
    }
});

// FLOW 3: Profile

profileButton.addEventListener("click", () => {
    window.location.href = "profile.html";
});

// FLOW 4: Export

exportButton.addEventListener("click", async () => {
    try {
        const response = await fetch("/api/export-orders");

        if (!response.ok) {
            throw new Error(
                `Export failed with status ${response.status}`
            );
        }
    } catch (error) {
        console.error("EXPORT_FLOW_FAILED:", error);
    }
});

// FLOW 5: Recommendation

crashButton.addEventListener("click", () => {
    const recommendation = undefined;

    // Intentional runtime failure.
    console.log(recommendation.products[0]);
});

// FLOW 6: Checkout

checkoutForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const address = document.getElementById("address").value;

    if (!address.trim()) {
        document.getElementById("checkoutStatus").textContent =
            "Address is required.";
        return;
    }

    try {
        const response = await fetch("/api/checkout", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ address })
        });

        if (!response.ok) {
            throw new Error(
                `Checkout failed with status ${response.status}`
            );
        }
    } catch (error) {
        console.error("CHECKOUT_FLOW_FAILED:", error);

        document.getElementById("checkoutStatus").textContent =
            "Unable to place order.";
    }
});