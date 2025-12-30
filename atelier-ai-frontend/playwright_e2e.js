const { chromium } = require('playwright');

const TEST_SCENARIOS = [
  {
    name: "Complete Booking Flow",
    messages: [
      "I need a room for 20 people on 15.03.2026. Projector required.",
      "Yes, I confirm the date",
      "Room A sounds good, lets proceed",
    ]
  },
  {
    name: "QnA Mid-Flow",
    messages: [
      "Room for 15 people on 01.04.2026",
      "Do you have parking available?",
    ]
  },
  {
    name: "Date Change Request",
    messages: [
      "Meeting room for 25 guests on 20.03.2026",
      "Actually, change the date to 10.04.2026",
    ]
  }
];

async function runTests() {
  console.log("Starting Playwright E2E tests...");
  const browser = await chromium.launch({ headless: true });
  const results = [];

  for (const scenario of TEST_SCENARIOS) {
    console.log("\n============================================================");
    console.log("SCENARIO: " + scenario.name);
    console.log("============================================================");

    const context = await browser.newContext();
    const page = await context.newPage();

    try {
      // Navigate to the chat interface
      await page.goto("http://localhost:3000");
      await page.waitForTimeout(2000);

      // Take initial screenshot
      var filename = "/tmp/pw_" + scenario.name.replace(/ /g, "_") + "_1_initial.png";
      await page.screenshot({ path: filename });
      console.log("Screenshot: " + filename);

      // Find the chat input - look for common patterns
      var chatInput = null;
      try {
        chatInput = await page.locator("textarea").first();
        await chatInput.waitFor({ timeout: 3000 });
      } catch (e) {
        chatInput = await page.locator("input[type=text]").first();
      }

      if (!chatInput) {
        throw new Error("Could not find chat input");
      }

      for (var i = 0; i < scenario.messages.length; i++) {
        var msg = scenario.messages[i];
        console.log("\nMessage " + (i+1) + ": " + msg.slice(0, 50) + "...");

        // Type message
        await chatInput.fill(msg);
        await page.waitForTimeout(500);

        // Submit (press Enter)
        await chatInput.press("Enter");

        // Wait for response
        await page.waitForTimeout(4000);

        // Get page text to see response
        var bodyText = await page.textContent("body");
        console.log("Page content preview: " + bodyText.slice(0, 200) + "...");

        // Screenshot
        filename = "/tmp/pw_" + scenario.name.replace(/ /g, "_") + "_" + (i+2) + "_step.png";
        await page.screenshot({ path: filename });
        console.log("Screenshot: " + filename);
      }

      results.push({ scenario: scenario.name, status: "COMPLETED" });

    } catch (err) {
      console.error("Error: " + err.message);
      filename = "/tmp/pw_" + scenario.name.replace(/ /g, "_") + "_error.png";
      await page.screenshot({ path: filename });
      results.push({ scenario: scenario.name, status: "ERROR: " + err.message });
    }

    await context.close();
  }

  await browser.close();

  // Summary
  console.log("\n============================================================");
  console.log("TEST SUMMARY");
  console.log("============================================================");
  results.forEach(function(r) {
    var icon = r.status === "COMPLETED" ? "Y" : "X";
    console.log("  " + icon + " " + r.scenario + ": " + r.status);
  });
}

runTests().catch(console.error);
