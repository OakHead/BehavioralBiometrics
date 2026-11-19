package com.behavioralguard.companion;

import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.text.InputFilter;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;
import org.json.JSONObject;

public class AlertActionActivity extends GuardActivity {
    private TextView message;
    private EditText code;
    private Button verify, deny;
    private String identifier;
    private boolean sending, approvalBlocked;

    static Intent intent(Context context, String identifier, boolean deny) {
        return new Intent(context, AlertActionActivity.class)
            .setData(Uri.parse("behavioralguard-v2-internal://alert/" + identifier + "/" + deny))
            .putExtra("id", identifier).putExtra("deny", deny);
    }

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        identifier = getIntent().getStringExtra("id");
        JSONObject alert = Client.activeAlert(this);
        LinearLayout root = screen();
        brand(root);
        LinearLayout card = card(root, true);
        card.setFocusableInTouchMode(true);
        if (identifier == null || alert == null || !identifier.equals(alert.optString("id"))) {
            title(card, "Request ended", 30);
            text(card, "This approval request is no longer available.", 16, RED, false);
            button(card, "Close", 0, view -> finish());
            return;
        }

        boolean test = "test".equals(alert.optString("kind"));
        Client.prefs(this).edit().putString("presented", identifier).apply();
        boolean confirmDeny = getIntent().getBooleanExtra("deny", false);
        title(card, test ? "Test approval" : "Is this you?", 35);
        text(card, "PC · " + Client.prefs(this).getString("pc", "Your PC"), 14, TEAL, true);
        text(card, alert.optString("reason"), 16, MUTED, false);
        if (confirmDeny) {
            text(card, test ? "This test will leave the PC unlocked." : "Denying this request locks the PC.", 15, MUTED, false);
        } else {
            text(card, "Enter the three-digit code shown on your PC.", 15, TEXT, false);
            code = new EditText(this);
            code.setId(View.generateViewId());
            code.setTextColor(TEXT);
            code.setHintTextColor(MUTED);
            code.setHint("– – –");
            code.setContentDescription("Three-digit PC code");
            code.setTextSize(33);
            code.setGravity(Gravity.CENTER);
            code.setInputType(InputType.TYPE_CLASS_NUMBER);
            code.setTypeface(bodyFont());
            code.setLetterSpacing(.24f);
            code.setFilters(new InputFilter[]{new InputFilter.LengthFilter(3)});
            code.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
            code.setImeOptions(EditorInfo.IME_ACTION_DONE);
            code.setBackground(gradient(FIELD, PANEL, 14));
            card.addView(code, new LinearLayout.LayoutParams(-1, dp(70)));
            code.setOnEditorActionListener((view, action, event) -> {
                if (action == EditorInfo.IME_ACTION_DONE) { send(true); return true; }
                return false;
            });
            verify = button(card, "Verify code", 1, view -> send(true));
        }
        message = text(card, "", 14, RED, false);
        message.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        message.setVisibility(View.GONE);
        deny = button(card, test ? "Deny test" : "Deny request", -1, view -> send(false));
        button(card, "Later", 0, view -> finish());
        card.requestFocus();
        reveal(card, 0);
    }

    private void showError(String error) {
        message.setText(error);
        message.setVisibility(View.VISIBLE);
    }

    private void send(boolean answer) {
        if (sending || (answer && (code == null || approvalBlocked))) return;
        String value = answer ? code.getText().toString() : null;
        if (answer && !value.matches("[0-9]{3}")) {
            showError("Enter all three digits from your PC.");
            code.requestFocus();
            return;
        }
        sending = true;
        message.setVisibility(View.GONE);
        if (verify != null) verify.setEnabled(false);
        deny.setEnabled(false);
        new Thread(() -> {
            try {
                Client.respond(this, identifier, answer, value);
                runOnUiThread(() -> {
                    Toast.makeText(this, answer ? "Activity verified." : "Request denied.", Toast.LENGTH_SHORT).show();
                    finish();
                });
            } catch (Exception error) {
                runOnUiThread(() -> {
                    if (isFinishing() || isDestroyed()) return;
                    sending = false;
                    int status = error instanceof Client.ApiError ? ((Client.ApiError) error).status : 0;
                    approvalBlocked = approvalBlocked || status == 429 || status == 409 || status == 401;
                    if (verify != null) verify.setEnabled(!approvalBlocked);
                    deny.setEnabled(status != 409 && status != 401);
                    String detail = status == 400 || status == 401 || status == 409 || status == 422 || status == 429
                        ? error.getMessage() : "Could not send your answer. Check Wi-Fi and try again.";
                    showError(detail);
                });
            }
        }, "Guard-answer").start();
    }
}
