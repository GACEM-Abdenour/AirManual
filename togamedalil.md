# AeroMind API Integration: The 3D Game "Ghost Director"

**Date:** February 24, 2026  
**Target:** Unity / WebGL / Game Engine Client  
**Base Prod URL:** `https://airmanual.onrender.com`

## 🧠 1. System Context
AeroMind operates as a headless REST API. It reads the user's chat and the 3D part they clicked, searches the aviation manuals, and returns both the text answer AND the exact 3D command needed to animate the scene (mapped directly to your `AI_GAME_MANIPULATION_SPEC.md`).

---

## 🔌 2. The API Contract

* **Endpoint:** `POST /api/chat`
* **Headers Required:**
    * `Content-Type: application/json`
    * `X-API-Key: <INSERT_SECRET_KEY>` *(Ask the backend lead for the production key)*
* **Request Payload (JSON):**
    ```json
    {
      "session_id": "player_01",
      "question": "How do I remove this?",
      "selected_part": "10-600646-201" 
    }
    ```
    *(Note: Send `null` for `selected_part` if no part is clicked)*
* **Expected Response (JSON):**
    ```json
    {
      "text_reply": "The magneto is removed by disconnecting the wiring harness...", 
      "sources": ["AMM 74-20-00, Page 48"],
      "game_command": {
        "action": "camera.focus",
        "targetName": "10-600646-201",
        "distance": 5.0,
        "durationMs": 1500
      }
    }
    ```

---

## 🔄 3. Upgrading `mockAiService` to Production

Replace your hardcoded `mockAiService` with this real HTTP request. This integrates directly with your existing `HelicopterScene`, `ChangeViews`, and `App` managers.

```javascript
// Upgraded AiService (JS/TS Concept)
async function realAiService(sessionId, userText, currentSelectedPartId) {
    
    // UI TIP: Trigger a "Thinking..." animation
    App.showLoadingIndicator(true);

    try {
        const response = await fetch('[https://airmanual.onrender.com/api/chat](https://airmanual.onrender.com/api/chat)', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-API-Key': '<INSERT_SECRET_KEY>'
            },
            body: JSON.stringify({
                session_id: sessionId,
                question: userText,
                selected_part: currentSelectedPartId
            })
        });

        if (!response.ok) throw new Error(`API Error: ${response.status}`);
        const data = await response.json();
        
        // 1. Send the text to your existing ChatWindow
        ChatWindow.displayMessage(data.text_reply);
        
        // 2. Route the 3D actions to your existing managers
        if (data.game_command !== null) {
            switch(data.game_command.action) {
                case "camera.focus":
                case "model.highlight":
                case "model.explode":
                    HelicopterScene.executeCommand(data.game_command);
                    break;
                case "scene.switch":
                    ChangeViews.switch(data.game_command.sceneId);
                    break;
                case "ui.mode":
                case "ui.panel":
                    App.updateUI(data.game_command);
                    break;
                case "manual.open":
                    ManualViewer.open(data.game_command.docId, data.game_command.page);
                    break;
            }
        }
    } catch (error) {
        console.error("AeroMind API failed:", error);
        ChatWindow.displayError("Network connection to AeroMind lost.");
    } finally {
        App.showLoadingIndicator(false);
    }
}


## 🚨 4. Crucial Integration Pro-Tips

* **Tip 1: Timeout Warning:** Set your HTTP request timeout to at least 30-45 seconds. If the AI triggers "Deep Research Mode" to read 50+ manual pages, it needs time to process.
* **Tip 2: The Exact Match Rule:** The string you send as `selected_part` must be the actual Part Number (P/N) (e.g., `"10-600646-201"`), not a generic mesh name like `"mesh_magneto_01"`. The AI uses this string to search the database.
* **Tip 3: Handling the `null` Command:** If a player asks a general question ("What are the safety rules?"), the AI will return `"game_command": null`. Always strictly null-check before passing data to your Command Router to prevent Null Reference Exceptions.
* **Tip 4: WebGL CORS Issues:** If running in a web browser, security might block the request (CORS error). Tell the backend lead what domain the game is hosted on (e.g., `https://mygame.com`) so they can whitelist it in the FastAPI server.
* **Tip 5: Test with Postman First:** Before writing code, use Postman/Hoppscotch to hit the Prod URL with your `X-API-Key` to verify the JSON structure firsthand.