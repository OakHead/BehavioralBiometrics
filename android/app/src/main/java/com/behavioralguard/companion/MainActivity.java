package com.behavioralguard.companion;

import android.Manifest;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;
import org.json.JSONObject;

public class MainActivity extends GuardActivity {
    private final Handler handler = new Handler(Looper.getMainLooper());
    private TextView headline, status, reason, alertTitle, alertState;
    private EditText pairing;
    private LinearLayout pairingCard, alertCard;
    private Button connect, listenButton, forgetButton;
    private String currentAlert = "", lastPresented = "";
    private String pairingError = "";
    private boolean pairingInProgress;

    private final Runnable refresh = new Runnable() {
        @Override public void run() {
            refreshStatus(true);
            handler.postDelayed(this, 750);
        }
    };

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        if (state != null) lastPresented = state.getString("lastPresented", "");
        LinearLayout root = screen();
        brand(root);

        LinearLayout hero = card(root, true);
        LinearLayout heroRow = new LinearLayout(this);
        heroRow.setGravity(Gravity.CENTER_VERTICAL);
        hero.addView(heroRow, new LinearLayout.LayoutParams(-1, -2));
        LinearLayout copy = new LinearLayout(this);
        copy.setOrientation(LinearLayout.VERTICAL);
        heroRow.addView(copy, new LinearLayout.LayoutParams(0, -2, 1));
        alertState = text(copy, "Phone alerts off", 12, LAVENDER, true);
        headline = title(copy, "Pair your PC", 33);
        status = text(copy, "", 15, MUTED, false);

        FrameLayout radar = new FrameLayout(this);
        LinearLayout.LayoutParams signal = new LinearLayout.LayoutParams(dp(102), dp(108));
        signal.setMarginStart(dp(8));
        heroRow.addView(radar, signal);
        radar.addView(new ShieldSignal(), new FrameLayout.LayoutParams(-1, -1));
        ImageView logo = new ImageView(this);
        logo.setImageResource(R.drawable.shield);
        logo.setScaleType(ImageView.ScaleType.FIT_CENTER);
        radar.addView(logo, new FrameLayout.LayoutParams(dp(43), dp(43), Gravity.CENTER));
        reveal(hero, 0);

        alertCard = card(root, true);
        alertTitle = title(alertCard, "Approval request", 24);
        reason = text(alertCard, "", 15, MUTED, false);
        button(alertCard, "Review request", 1, view -> openApproval(false));
        alertCard.setVisibility(View.GONE);

        LinearLayout controls = card(root, false);
        title(controls, "Phone alerts", 22);
        listenButton = button(controls, "Listen for alerts", 1, view -> toggleListening());
        button(controls, "Notification settings", 0, view -> startActivity(new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
            .putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName())));
        button(controls, "Pair a PC", 0, view -> {
            if (pairingCard.getVisibility() != View.VISIBLE) {
                pairingCard.setVisibility(View.VISIBLE);
                reveal(pairingCard, 0);
            }
            pairingCard.post(() -> pairingCard.requestRectangleOnScreen(
                new android.graphics.Rect(0, 0, pairingCard.getWidth(), dp(200)), false));
        });
        reveal(controls, 45);

        pairingCard = card(root, false);
        title(pairingCard, "Pair with your PC", 22);
        text(pairingCard, "On the PC, open Profile → Phone alerts → Pair phone. Keep both devices on the same network.", 14, MUTED, false);
        button(pairingCard, "Scan pairing QR", 1, view -> scan());
        pairing = new EditText(this);
        pairing.setTextSize(15);
        pairing.setTextColor(TEXT);
        pairing.setHintTextColor(MUTED);
        pairing.setHint("Paste a pairing link");
        pairing.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD);
        pairing.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS);
        pairing.setSingleLine(true);
        pairing.setTypeface(bodyFont());
        pairing.setPadding(dp(12), dp(10), dp(12), dp(10));
        pairing.setBackground(shape(FIELD, 12));
        pairingCard.addView(pairing, new LinearLayout.LayoutParams(-1, dp(52)));
        connect = button(pairingCard, "Connect with link", 0, view -> connect());
        TextView pairingStatus = text(pairingCard, "", 14, RED, false);
        pairingStatus.setVisibility(View.GONE);
        pairingStatus.setTag("pairingStatus");
        forgetButton = button(pairingCard, "Forget this PC", -1, view -> {
            stopService(new Intent(this, ListenService.class));
            Client.prefs(this).edit().clear().apply();
            pairingError = "";
            lastPresented = "";
            refreshStatus(false);
        });
        if (Client.prefs(this).contains("secret")) pairingCard.setVisibility(View.GONE);
        else reveal(pairingCard, 85);
        readPairingIntent(getIntent());
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        readPairingIntent(intent);
    }

    @Override protected void onResume() { super.onResume(); handler.post(refresh); }
    @Override protected void onPause() { handler.removeCallbacks(refresh); super.onPause(); }

    @Override protected void onSaveInstanceState(Bundle state) {
        state.putString("lastPresented", lastPresented);
        super.onSaveInstanceState(state);
    }

    private void readPairingIntent(Intent intent) {
        if (Intent.ACTION_VIEW.equals(intent.getAction()) && intent.getData() != null) {
            pairingCard.setVisibility(View.VISIBLE);
            pairing.setText(intent.getData().toString());
        }
    }

    private void scan() {
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.CAMERA}, 11);
        } else {
            startActivityForResult(new Intent(this, ScannerActivity.class), 20);
        }
    }

    private void toggleListening() {
        SharedPreferences prefs = Client.prefs(this);
        if (prefs.getBoolean("listening", false)) {
            stopService(new Intent(this, ListenService.class));
            prefs.edit().putBoolean("listening", false).remove("alert").apply();
            refreshStatus(false);
        } else {
            listen();
        }
    }

    private void listen() {
        if (!Client.prefs(this).contains("secret")) {
            pairingCard.setVisibility(View.VISIBLE);
            Toast.makeText(this, "Pair your PC first.", Toast.LENGTH_SHORT).show();
            return;
        }
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 12);
            return;
        }
        startForegroundService(new Intent(this, ListenService.class));
    }

    @Override public void onRequestPermissionsResult(int request, String[] permissions, int[] result) {
        super.onRequestPermissionsResult(request, permissions, result);
        if (result.length > 0 && result[0] == PackageManager.PERMISSION_GRANTED) {
            if (request == 11) scan();
            if (request == 12) listen();
        } else {
            Toast.makeText(this, request == 11 ? "You can paste the pairing link instead." : "Allow notifications to see incoming requests.",
                Toast.LENGTH_LONG).show();
        }
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == 20 && result == RESULT_OK && data != null) {
            pairing.setText(data.getStringExtra("pair"));
            connect();
        }
    }

    private void connect() {
        final String link = pairing.getText().toString();
        pairingInProgress = true;
        pairingError = "";
        connect.setEnabled(false);
        refreshStatus(false);
        new Thread(() -> {
            try {
                Client.Credentials credentials = Client.parse(link);
                JSONObject result = Client.request(credentials, "/v1/pair", new JSONObject().put("name", Build.MODEL));
                stopService(new Intent(this, ListenService.class));
                Client.save(this, credentials);
                Client.prefs(this).edit().putString("pc", result.optString("pc", "Your PC"))
                    .putLong("seen", System.currentTimeMillis()).putString("error", "").apply();
                runOnUiThread(() -> {
                    pairing.setText("");
                    pairingCard.setVisibility(View.GONE);
                    lastPresented = "";
                    pairingDone();
                    if (!isFinishing() && hasWindowFocus()) listen();
                });
            } catch (Exception error) {
                runOnUiThread(() -> {
                    pairingError = "Could not connect. Check the pairing code, Wi-Fi and Windows Firewall.";
                    pairingDone();
                });
            }
        }, "Guard-pair").start();
    }

    private void pairingDone() {
        pairingInProgress = false;
        connect.setEnabled(true);
        refreshStatus(false);
    }

    private void refreshStatus(boolean present) {
        SharedPreferences prefs = Client.prefs(this);
        boolean paired = prefs.contains("secret"), listening = prefs.getBoolean("listening", false);
        boolean connected = listening && System.currentTimeMillis() - prefs.getLong("seen", 0) < 45000;
        String error = listening ? prefs.getString("error", "") : "";
        headline.setText(pairingInProgress ? "Connecting…" : !paired ? "Pair your PC" :
            !listening ? "Alerts paused" : !error.isEmpty() || !connected ? "Waiting for PC" : "Connected");
        status.setText(!error.isEmpty() ? error : !paired ? "Pair once to receive approval requests." :
            "PC · " + prefs.getString("pc", "Your PC"));
        status.setTextColor(error.isEmpty() ? MUTED : RED);
        alertState.setText(listening ? "●  Listening for alerts" : "○  Phone alerts off");
        alertState.setTextColor(listening ? TEAL : LAVENDER);
        forgetButton.setVisibility(paired ? View.VISIBLE : View.GONE);
        listenButton.setText(listening ? "Pause phone alerts" : "Listen for alerts");
        listenButton.setEnabled(!pairingInProgress);
        TextView pairingStatus = (TextView) pairingCard.findViewWithTag("pairingStatus");
        pairingStatus.setText(pairingError);
        pairingStatus.setVisibility(pairingError.isEmpty() ? View.GONE : View.VISIBLE);

        JSONObject alert = Client.activeAlert(this);
        if (alert == null) {
            currentAlert = "";
            alertCard.setVisibility(View.GONE);
        } else {
            currentAlert = alert.optString("id");
            alertTitle.setText("test".equals(alert.optString("kind")) ? "Test approval" : "Approval request");
            reason.setText(alert.optString("reason"));
            if (alertCard.getVisibility() != View.VISIBLE) {
                alertCard.setVisibility(View.VISIBLE);
                reveal(alertCard, 0);
            }
            if (present && hasWindowFocus() && !currentAlert.equals(lastPresented)
                && !currentAlert.equals(prefs.getString("presented", ""))) openApproval(false);
        }
    }

    private void openApproval(boolean deny) {
        if (currentAlert.isEmpty()) return;
        lastPresented = currentAlert;
        startActivity(AlertActionActivity.intent(this, currentAlert, deny));
    }
}
