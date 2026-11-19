package com.behavioralguard.companion;

import android.animation.ValueAnimator;
import android.app.Activity;
import android.content.res.ColorStateList;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.graphics.drawable.StateListDrawable;
import android.os.Build;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.view.animation.DecelerateInterpolator;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

abstract class GuardActivity extends Activity {
    static final int BG = 0xff0e0d18, PANEL = 0xff1c1b2d, FIELD = 0xff2a2841, BORDER = 0xff383450,
        TEXT = 0xfff6f3ff, MUTED = 0xffbcb5d0, TEAL = 0xff89e6dd, RED = 0xffff839e,
        VIOLET = 0xffc4a3ff, LAVENDER = 0xffe4d2ff, AMBER = 0xffffd092, HERO = 0xff271d3d;
    private Typeface titleFont, bodyFont, strongFont;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        titleFont = getResources().getFont(R.font.anton);
        bodyFont = getResources().getFont(R.font.chakra_petch);
        strongFont = getResources().getFont(R.font.chakra_petch_semibold);
    }

    Typeface bodyFont() { return bodyFont; }

    int dp(float value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    boolean motionAllowed() { return ValueAnimator.areAnimatorsEnabled(); }

    void reveal(View view, int delay) {
        if (!motionAllowed()) return;
        view.setAlpha(0);
        view.setTranslationY(dp(10));
        view.animate().alpha(1).translationY(0).setDuration(220).setStartDelay(delay)
            .setInterpolator(new DecelerateInterpolator()).start();
    }

    GradientDrawable shape(int color, int radius) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(color);
        drawable.setCornerRadius(dp(radius));
        return drawable;
    }

    GradientDrawable gradient(int start, int end, int radius) {
        GradientDrawable drawable = new GradientDrawable(GradientDrawable.Orientation.TL_BR, new int[]{start, end});
        drawable.setCornerRadius(dp(radius));
        if (radius > 0) drawable.setStroke(dp(1), BORDER);
        return drawable;
    }

    LinearLayout screen() {
        ScrollView scroll = new ScrollView(this);
        scroll.setBackground(gradient(0xff201735, BG, 0));
        scroll.setFillViewport(true);
        FrameLayout frame = new FrameLayout(this);
        scroll.addView(frame);
        LinearLayout column = new LinearLayout(this);
        column.setOrientation(LinearLayout.VERTICAL);
        frame.addView(column, new FrameLayout.LayoutParams(-1, -2, Gravity.TOP | Gravity.CENTER_HORIZONTAL));
        scroll.setOnApplyWindowInsetsListener((view, insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                int keyboard = insets.getInsets(WindowInsets.Type.ime()).bottom;
                frame.setPadding(dp(20) + bars.left, dp(18) + bars.top, dp(20) + bars.right, dp(24) + Math.max(bars.bottom, keyboard));
            } else {
                frame.setPadding(dp(20) + insets.getSystemWindowInsetLeft(), dp(18) + insets.getSystemWindowInsetTop(),
                    dp(20) + insets.getSystemWindowInsetRight(), dp(24) + insets.getSystemWindowInsetBottom());
            }
            return insets;
        });
        frame.addOnLayoutChangeListener((view, left, top, right, bottom, oldLeft, oldTop, oldRight, oldBottom) -> {
            int width = Math.min(dp(520), right - left - frame.getPaddingLeft() - frame.getPaddingRight());
            if (width > 0 && column.getLayoutParams().width != width) {
                FrameLayout.LayoutParams layout = (FrameLayout.LayoutParams) column.getLayoutParams();
                layout.width = width;
                column.setLayoutParams(layout);
            }
        });
        setContentView(scroll);
        return column;
    }

    TextView text(LinearLayout parent, String value, int size, int color, boolean bold) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        view.setTypeface(bold ? strongFont : bodyFont);
        view.setLineSpacing(dp(2), 1);
        LinearLayout.LayoutParams layout = new LinearLayout.LayoutParams(-1, -2);
        layout.bottomMargin = dp(8);
        parent.addView(view, layout);
        return view;
    }

    TextView title(LinearLayout parent, String value, int size) {
        TextView view = text(parent, value, size, TEXT, false);
        view.setTypeface(titleFont);
        if (Build.VERSION.SDK_INT >= 28) view.setAccessibilityHeading(true);
        return view;
    }

    void brand(LinearLayout parent) {
        LinearLayout row = new LinearLayout(this);
        row.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout.LayoutParams layout = new LinearLayout.LayoutParams(-1, -2);
        layout.bottomMargin = dp(17);
        parent.addView(row, layout);
        ImageView mark = new ImageView(this);
        mark.setImageResource(R.drawable.shield);
        mark.setScaleType(ImageView.ScaleType.FIT_CENTER);
        layout = new LinearLayout.LayoutParams(dp(39), dp(39));
        layout.setMarginEnd(dp(11));
        row.addView(mark, layout);
        TextView name = title(row, getString(R.string.app_name), 26);
        name.setTextColor(LAVENDER);
        name.setLayoutParams(new LinearLayout.LayoutParams(0, -2, 1));
    }

    LinearLayout card(LinearLayout parent, boolean hero) {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(20), dp(19), dp(20), dp(17));
        card.setBackground(hero ? gradient(0xff3d2859, HERO, 24) : gradient(PANEL, 0xff242036, 18));
        LinearLayout.LayoutParams layout = new LinearLayout.LayoutParams(-1, -2);
        layout.bottomMargin = dp(14);
        parent.addView(card, layout);
        return card;
    }

    Button button(LinearLayout parent, String title, int kind, View.OnClickListener action) {
        Button button = new Button(this);
        button.setText(title);
        button.setAllCaps(false);
        button.setTextSize(15);
        button.setTypeface(strongFont);
        button.setLetterSpacing(0);
        button.setMinHeight(dp(48));
        button.setTextColor(new ColorStateList(
            new int[][]{new int[]{-android.R.attr.state_enabled}, new int[]{}},
            new int[]{0xffa89abb, kind == 1 ? BG : kind == -1 ? RED : TEXT}));
        button.setBackgroundTintList(null);
        GradientDrawable fill = kind == 1 ? gradient(LAVENDER, VIOLET, 12) :
            kind == -1 ? gradient(0xff432538, 0xff342037, 12) : gradient(FIELD, 0xff302644, 12);
        StateListDrawable states = new StateListDrawable();
        states.addState(new int[]{-android.R.attr.state_enabled}, shape(PANEL, 12));
        states.addState(new int[]{}, new RippleDrawable(ColorStateList.valueOf(kind == 1 ? 0x30251c41 : 0x30ffffff), fill, null));
        button.setBackground(states);
        button.setPadding(dp(10), dp(9), dp(10), dp(9));
        LinearLayout.LayoutParams layout = new LinearLayout.LayoutParams(-1, -2);
        layout.topMargin = dp(6);
        layout.bottomMargin = dp(4);
        parent.addView(button, layout);
        button.setOnClickListener(action);
        return button;
    }

    final class ShieldSignal extends View {
        private final Paint pen = new Paint(Paint.ANTI_ALIAS_FLAG);

        ShieldSignal() {
            super(GuardActivity.this);
            setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        }

        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            float x = getWidth() / 2f, y = getHeight() / 2f, radius = Math.min(x, y) - dp(7);
            if (radius <= 0) return;
            pen.setStrokeWidth(dp(1));
            pen.setColor(0xff73589c);
            pen.setStyle(Paint.Style.STROKE);
            canvas.drawCircle(x, y, radius*.45f, pen);
            canvas.drawCircle(x, y, radius*.72f, pen);
            canvas.drawCircle(x, y, radius, pen);
            boolean motion = motionAllowed();
            float angle = motion ? (SystemClock.uptimeMillis() % 7600) * (360f / 7600) : 205;
            pen.setColor(VIOLET);
            pen.setStrokeWidth(dp(2));
            pen.setStrokeCap(Paint.Cap.ROUND);
            canvas.drawArc(x-radius, y-radius, x+radius, y+radius, angle, 72, false, pen);
            pen.setStyle(Paint.Style.FILL);
            pen.setColor(TEAL);
            double radians = Math.toRadians(angle+72);
            canvas.drawCircle(x+(float)Math.cos(radians)*radius, y+(float)Math.sin(radians)*radius, dp(2.5f), pen);
            if (isShown() && getWindowVisibility() == View.VISIBLE && motion) postInvalidateDelayed(42);
        }
    }
}
