package com.behavioralguard.companion;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.graphics.drawable.Icon;
import android.net.Uri;
import android.os.*;
import org.json.JSONObject;
import javax.net.ssl.HttpsURLConnection;

public class ListenService extends Service {
    volatile boolean stopping;
    volatile HttpsURLConnection currentConnection;
    Thread worker;
    static final String CONNECTION="connection", ALERTS="approval_requests";
    NotificationManager notifications;
    @Override public void onCreate() {
        super.onCreate(); notifications=getSystemService(NotificationManager.class);
        notifications.createNotificationChannel(new NotificationChannel(CONNECTION,"PC connection",NotificationManager.IMPORTANCE_LOW));
        NotificationChannel alerts=new NotificationChannel(ALERTS,"PC approval pop-ups",NotificationManager.IMPORTANCE_HIGH);
        alerts.setDescription("Requests to verify unusual activity on your paired PC");
        alerts.enableVibration(true); alerts.setVibrationPattern(new long[]{0,200,100,200}); alerts.setLockscreenVisibility(Notification.VISIBILITY_PRIVATE); notifications.createNotificationChannel(alerts);
    }
    PendingIntent open() {return PendingIntent.getActivity(this,1,new Intent(this,MainActivity.class),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);}
    Notification connection(String text) {
        return new Notification.Builder(this,CONNECTION).setSmallIcon(R.drawable.ic_shield).setContentTitle("Behavioral Guard")
            .setContentText(text).setContentIntent(open()).setOngoing(true).setOnlyAlertOnce(true).build();
    }
    @Override public int onStartCommand(Intent intent,int flags,int startId) {
        if(Build.VERSION.SDK_INT>=29) startForeground(1,connection("Listening for your PC"),ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE);
        else startForeground(1,connection("Listening for your PC"));
        Client.prefs(this).edit().putBoolean("listening",true).apply();
        if(worker==null || !worker.isAlive()) {stopping=false; worker=new Thread(this::loop,"Guard-PC-connection"); worker.start();}
        return START_STICKY;
    }
    void loop() {
        String last=""; int retry=0;
        while(!stopping) {
            try {
                Client.Credentials credentials=Client.load(this);
                currentConnection=Client.connection(credentials,"/v1/poll?last="+Uri.encode(last));
                JSONObject state=Client.exchange(currentConnection,null);
                if(stopping) break;
                JSONObject alert=state.optJSONObject("alert");
                String identifier=alert==null?"":alert.optString("id");
                android.content.SharedPreferences p=Client.prefs(this);
                p.edit().putLong("seen",System.currentTimeMillis()).putString("error","").apply();
                if(alert==null || identifier.equals(p.getString("answered",""))) {p.edit().remove("alert").apply(); notifications.cancel(2);}
                else {p.edit().putString("alert",alert.toString()).apply(); if(!identifier.equals(last)) showAlert(alert);}
                last=identifier; retry=0; notifications.notify(1,connection("Connected to "+state.optString("pc","your PC")));
            } catch(Exception error) {
                if(stopping) break;
                String message=error instanceof Client.ApiError && ((Client.ApiError)error).status==401?"Pair this phone again from the PC.":"Waiting for your PC. Check Wi-Fi and Windows Firewall.";
                Client.prefs(this).edit().putString("error",message).apply(); notifications.notify(1,connection(message));
                try {Thread.sleep(Math.min(10000,1000L*(++retry)));} catch(InterruptedException stopped) {break;}
            } finally {if(currentConnection!=null) {currentConnection.disconnect(); currentConnection=null;}}
        }
    }
    PendingIntent approval(String id, boolean deny) {
        return PendingIntent.getActivity(this, deny ? 3 : 2, AlertActionActivity.intent(this, id, deny),
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }
    Notification.Action action(String id,boolean deny) {
        Notification.Action.Builder action=new Notification.Action.Builder(Icon.createWithResource(this,R.drawable.ic_shield),
            deny ? "Deny" : "Enter code", approval(id, deny));
        if(Build.VERSION.SDK_INT>=31) action.setAuthenticationRequired(true);
        return action.build();
    }
    void showAlert(JSONObject alert) {
        String id=alert.optString("id"), reason=alert.optString("reason");
        Notification notification=new Notification.Builder(this,ALERTS).setSmallIcon(R.drawable.ic_shield)
            .setContentTitle("test".equals(alert.optString("kind")) ? "Test approval" : "PC approval requested")
            .setContentText("Enter the code shown on your PC.").setStyle(new Notification.BigTextStyle().bigText(reason))
            .setContentIntent(approval(id, false)).setColor(GuardActivity.TEAL).setTimeoutAfter(300000)
            .setCategory(Notification.CATEGORY_EVENT).setVisibility(Notification.VISIBILITY_PRIVATE)
            .addAction(action(id,false)).addAction(action(id,true)).build();
        notifications.notify(2,notification);
    }
    @Override public void onDestroy() {
        stopping=true; if(currentConnection!=null) currentConnection.disconnect(); if(worker!=null) worker.interrupt();
        Client.prefs(this).edit().putBoolean("listening",false).remove("alert").apply(); notifications.cancel(2); stopForeground(STOP_FOREGROUND_REMOVE); super.onDestroy();
    }
    @Override public IBinder onBind(Intent intent) {return null;}
}
