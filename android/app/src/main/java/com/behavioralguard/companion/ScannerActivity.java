package com.behavioralguard.companion;

import android.graphics.Canvas;
import android.graphics.Paint;
import android.content.Intent;
import android.hardware.Camera;
import android.os.Bundle;
import android.view.*;
import android.widget.*;
import com.google.zxing.*;
import com.google.zxing.common.HybridBinarizer;
import java.util.concurrent.atomic.AtomicBoolean;

@SuppressWarnings("deprecation")
public class ScannerActivity extends GuardActivity implements SurfaceHolder.Callback, Camera.PreviewCallback {
    Camera camera;
    SurfaceView preview;
    TextView instruction;
    final AtomicBoolean busy=new AtomicBoolean();
    volatile boolean done;
    long lastFrame;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(BG);
        preview = new SurfaceView(this);
        root.addView(preview, new FrameLayout.LayoutParams(-1, -1));
        root.addView(new ScanGuide(), new FrameLayout.LayoutParams(-1, -1));
        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.VERTICAL);
        header.setPadding(dp(18), dp(12), dp(18), dp(12));
        header.setBackground(gradient(HERO, PANEL, 16));
        title(header, "Scan pairing code", 24);
        instruction = text(header, "Point the camera at the QR code on your PC.", 15, MUTED, false);
        FrameLayout.LayoutParams top = new FrameLayout.LayoutParams(-1, -2, Gravity.TOP);
        root.addView(header, top);
        LinearLayout footer = new LinearLayout(this);
        footer.setOrientation(LinearLayout.VERTICAL);
        button(footer, "Cancel", 0, view -> finish());
        FrameLayout.LayoutParams bottom = new FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM);
        root.addView(footer, bottom);
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            top.setMargins(dp(16), dp(12) + insets.getSystemWindowInsetTop(), dp(16), 0);
            header.setLayoutParams(top);
            bottom.setMargins(dp(16), 0, dp(16), dp(12) + insets.getSystemWindowInsetBottom());
            footer.setLayoutParams(bottom);
            return insets;
        });
        setContentView(root); preview.getHolder().addCallback(this);
    }

    private final class ScanGuide extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);

        ScanGuide() {
            super(ScannerActivity.this);
            setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        }

        @Override protected void onDraw(Canvas canvas) {
            float side = Math.min(getWidth(), getHeight())*.68f;
            float left = (getWidth()-side)/2, top = (getHeight()-side)/2;
            paint.setColor(VIOLET);
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(dp(2));
            canvas.drawRoundRect(left, top, left+side, top+side, dp(14), dp(14), paint);
        }
    }
    @Override public void surfaceCreated(SurfaceHolder holder) {
        if(camera!=null) return;
        try {
            camera=Camera.open(); Camera.Parameters p=camera.getParameters();
            for(Camera.Size size:p.getSupportedPreviewSizes()) if(size.width==640 && size.height==480) {p.setPreviewSize(640,480);break;}
            if(p.getSupportedFocusModes().contains(Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE)) p.setFocusMode(Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE);
            camera.setParameters(p); camera.setDisplayOrientation(90); camera.setPreviewDisplay(holder); camera.setPreviewCallback(this); camera.startPreview();
        } catch(Exception error) {instruction.setText("Could not open the camera. You can paste the pairing link instead."); release();}
    }
    @Override public void onPreviewFrame(byte[] data,Camera source) {
        long now=android.os.SystemClock.elapsedRealtime(); if(done || now-lastFrame<250 || !busy.compareAndSet(false,true)) return; lastFrame=now;
        Camera.Size size=source.getParameters().getPreviewSize(); final byte[] frame=data.clone();
        new Thread(()-> {
            try {
                PlanarYUVLuminanceSource pixels=new PlanarYUVLuminanceSource(frame,size.width,size.height,0,0,size.width,size.height,false);
                Result result=new MultiFormatReader().decode(new BinaryBitmap(new HybridBinarizer(pixels)));
                String link=result.getText(); Client.parse(link);
                done=true; runOnUiThread(()->{setResult(RESULT_OK,new Intent().putExtra("pair",link));finish();});
            } catch(Exception ignored) {} finally {busy.set(false);}
        },"Guard-QR").start();
    }
    void release() {if(camera!=null) {camera.setPreviewCallback(null); camera.stopPreview(); camera.release(); camera=null;}}
    @Override public void surfaceChanged(SurfaceHolder holder,int format,int width,int height) {}
    @Override public void surfaceDestroyed(SurfaceHolder holder) {release();}
    @Override protected void onResume() {super.onResume();done=false;if(preview!=null && preview.getHolder().getSurface().isValid()) surfaceCreated(preview.getHolder());}
    @Override protected void onPause() {done=true;release();super.onPause();}
}
