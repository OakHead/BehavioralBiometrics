# Phone approvals

The Windows app and Android companion communicate over your local network. Keep Behavioral Guard open on the PC and listening on the phone. If you previously installed the companion labeled **Behavioral Guard V2**, install this APK over it to keep its saved pairing and settings.

## Pair once

1. Install **BehavioralGuard.apk** on your Android phone.
2. On Windows, start Behavioral Guard with **Start BehaviorGuard.cmd** and create or select a profile.
3. Open **Profile → Phone alerts → Pair phone** and enter your profile password.
4. On Android, open **Behavioral Guard** and tap **Scan pairing QR**. Allow camera access and scan the code on your PC.
5. Allow notifications and leave **Listen for alerts** on. The companion shows a persistent connection notification.
6. On the PC, choose **Test alert**. Tap the phone pop-up, enter the three digits from the PC, and tap **Verify code**. You can also test **Deny**. Both test responses leave the PC unlocked.
7. Choose **Start protection** on the PC when ready.

To pair manually, choose **Copy pairing link** on the PC, transfer the link privately to the phone, and tap **Connect with link** after pasting it. The pairing link expires after ten minutes.

## Approval requests

The phone opens the approval screen automatically while Behavioral Guard is on screen. When another app is on screen, Android can show a heads-up notification with **Enter code** and **Deny**. Tap to open the request and unlock the phone if prompted. On Samsung, check the **PC approval pop-ups** channel in the app's notification settings if banners are missing.

- **Verify** uses a three-digit code visible only on the PC. After three incorrect codes, you can approve on the PC or deny from either device.
- **Deny** requests the Windows lock screen and keeps the rejected activity out of training.
- The first accepted response closes the request. Phone responses expire after five minutes. You can still answer on the PC.

## Connection

- Use the same non-guest Wi-Fi on both devices, or connect the PC by Ethernet to the same network. If there are several PC addresses above the QR code, choose the one for this network.
- If prompted by Windows Firewall, allow the PC app on the private network for TCP `8766`.
- Choose **Turn off phone alerts** in the Windows app to revoke the connection. On Android, **Pair a PC → Forget this PC** clears the stored pairing on your phone.

The PC connection uses HTTPS with a certificate fingerprint delivered in the pairing QR. The server keeps the approval code in memory and verifies the code entered from the phone over that connection.
