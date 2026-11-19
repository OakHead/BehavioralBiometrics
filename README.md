# Behavioral Guard

Learn your normal typing and mouse habits, then watch for changes on this Windows PC.

## Run on another PC

Extract the complete `BehavioralGuard.zip` to a writable folder on a 64-bit Windows 10 or 11 PC. Open **Start BehaviorGuard.cmd**. The `runtime` folder includes Python, Tkinter, and the app's packages. The desktop app can start offline. From a source-only checkout, install 64-bit Python 3.12 with Tkinter and the Python launcher, then run **Setup from source.cmd** once to install the dependencies.

A fresh extraction starts with a new `data` folder. To bring over your training and settings, close both copies and copy `data/profiles` and `data/settings.json` from the earlier copy into the new one. Open **Profile → Phone alerts → Pair phone** if this installation needs a new phone pairing.

## How to use it

1. Open **Start BehaviorGuard.cmd**.
2. Select your profile, or choose **+ New profile**. Choose a name and a password with at least 10 characters.
3. Open **Training**. Choose a **Duration** in minutes or seconds, from 10 seconds to 60 minutes.
4. Select the tracking checkbox, choose **Start training**, and enter your password.
5. Type and move your mouse normally, here or in your other apps. The timer shows how much time is left. **Pause** saves your progress.
6. When there is enough training, protection starts automatically. If more activity is needed, your progress is kept and the app asks for another session.

After pausing, open **Overview** and choose **Start protection** to resume. To record more of your usual behavior, open **Training** and choose **Add training**. Your earlier training is kept. Existing profiles and passwords still work.

## Where to find things

| Page | What it is for |
| --- | --- |
| Overview | Start or pause protection, see live activity, and choose alert timing. |
| Training | Choose a duration, start a session, or add more training. |
| Mouse maps | Compare the saved pattern with current mouse activity. |
| Alerts & history | Read the latest alert, view typing changes, and review recent activity. |
| Profile | Create or delete a profile and see what is saved. |

Violet highlights actions, mint marks active checks, and red marks errors or destructive actions. Activity cards use distinct colors. The dashboard uses Anton for headings and Chakra Petch for controls and body text. Motion follows the Windows animation setting. **Pause** is available in the header on every page.

Password boxes, questions and error messages use the same dark theme. Passwords are hidden by default; use **Show password** to reveal them. Enter continues and Escape cancels. Cancelling a password box does not display an incorrect-password error.

The launcher shows a short starting screen, then opens the app. Its terminal closes immediately. Starting it again brings the existing app forward. If startup fails, details are saved to `data/startup-error.log`.

## What gets checked

Phone alerts are available under **Profile → Phone alerts**. Install **BehavioralGuard.apk** and pair it with the desktop QR code. Enter the code shown on the desktop to approve activity on your phone. See **Phone_Setup.md** for setup and the safe test alert.

- Individual key hold times, including a key that is still being held.
- Typing speed, measured as key presses per second over a rolling two-second window.
- The time between key presses and changes in typing rhythm.
- The highest mouse speed learned during training, measured over short 100 ms bursts to reduce sampling noise.

Mouse protection checks speed, movement outside your recorded areas, and how long the cursor stays still. Screen-edge time and direction measurements are also recorded.

**Typing speed and rhythm have separate lines** on **Alerts & history**. Blue shows speed changes; mint shows rhythm changes. Either can raise the graph above the alert level. A speed or rhythm change must continue for the selected 2.5 / 5 / 7.5-second delay before the identity question appears. Stopping typing is not a slow-typing alert.

Speed is compared with the range learned for the selected profile. Faster and slower typing can trigger an alert; random letters typed at your normal pace can still look normal. Direct speed samples are saved during training or approved updates. Older profiles get an initial estimate from their saved time between key presses; use **Add training** to record direct measurements. Key hold detection stays separate. Holding a key for repeated characters does not count as many new key presses, and Shift/Ctrl/Alt do not inflate typing speed.

## Mouse checks while typing

On **Overview**, choose one of the rounded buttons under **Mouse checks while typing**:

- **Check both:** typing and mouse checks run together, including mouse idle checks.
- **Pause mouse while typing:** mouse speed, area and idle alerts pause while you type or hold a typing key. They resume after 1.5 seconds without typing, with fresh mouse timers. This is the default for profiles without a saved choice.

The choice is saved separately for each profile. Changing it does not stop typing-speed or key-hold checks. Mouse maps continue recording separately, and training still collects both inputs. The app discards mouse-speed bursts from the suspended period so they cannot cause an alert on resume.

**Mouse-speed alerts are immediate:** when a measured burst exceeds the saved maximum, the app asks whether it is you. The maximum is stored per profile and is not shown as an extra dashboard value.

**Key hold alerts are immediate above twice the saved maximum.** With a saved maximum of 500 ms, 1,000 ms is accepted and 1,001 ms triggers the question, even while the key is still held. Modifier keys such as Ctrl and Shift are excluded from this rule.

**Detection mode selects the timed checks exactly as follows:**

| Mode | Typing-rhythm / outside-area delay | Maximum idle time in the hottest area |
| --- | --- | --- |
| Low | 2.5 seconds | 12.5 seconds |
| Balanced | 5 seconds | 25 seconds |
| High | 7.5 seconds | 37.5 seconds |

These names follow the requested timing order. Mouse-speed and double-maximum key-hold checks remain immediate in every mode.

Alerts show **Is this you?** and a short reason in a centered prompt over the dimmed Windows desktop. The prompt runs on your normal Windows desktop. Choosing **No, lock PC** requests the real Windows lock screen. The latest reason and comparison measurements are saved with the profile and shown on **Overview** and **Alerts & history**.

## “Is this you?”

- **Yes to a mouse-speed alert:** the detected speed becomes your new saved maximum. Protection resumes immediately. Going above the new maximum produces another prompt; the same or slower speed is accepted. Only explicit approval or a new learning period changes the speed cap.
- **Yes to a key-hold alert:** the new saved maximum is the detected integer duration minus one millisecond. Approving 1,001 ms saves a maximum of 1,000 ms, so the next alert is above 2,000 ms. This approval does not start a grace period.
- **Yes to a typing-speed or rhythm alert:** the app saves the change and gives you a **60-second grace period for timed checks**. Mouse-speed and double-maximum key-hold protection stay active, subject to your chosen mouse mode.
- **Yes to a mouse-area or idle alert:** you explicitly approve learning the new cursor behavior for one minute. The recorded pattern can then be updated with that approved activity. Speed and double-maximum key-hold checks stay active during that minute.
- **No:** the app pauses and requests the Windows lock screen using `LockWorkStation`, the same workstation lock action as Windows+L. It does not learn the rejected behavior. If Windows refuses the request, the app displays an error.

Open the app normally from your Desktop using **Start BehaviorGuard.cmd**. A copy launched inside a restricted automation container may be unable to lock Windows. A failed lock now records the Windows error in `data/errors.log`. A successful API call means the lock was requested; Windows completes the operation asynchronously.

The Yes response is manual confirmation. Anyone using the unlocked PC can select it, so this prototype should be used alongside your normal Windows security.

Older profiles did not save actual peak speed. They get a conservative initial cap from their saved mouse measurements. Use **Learn more** to calibrate the actual maximum from a new timed learning period. Existing passwords, training samples and heat maps are preserved.

## Mouse maps are saved

On **Mouse maps**, each profile has two maps side by side: **Saved pattern** on the left and **Current activity** on the right. Current activity is saved separately. The saved pattern changes during training or after you approve new behavior. Both maps are saved every five seconds while running and on pause, close, switching profiles or handling an alert. Reopening restores your selected profile and maps.

Different monitor arrangements have separate maps, including layouts with negative desktop coordinates. A layout with no recorded pattern is treated as unrecorded until you train or approve its areas.

**Clear current activity** clears only the right-hand map for the current screen arrangement, after confirmation. Your saved pattern and detection limits are kept.

The saved 48 x 27 time grid is smoothed with a Gaussian neighborhood and interpolated for display, producing orange centers with yellow, green and blue surrounding areas. The exact same smoothed recorded heat drives detection; the current map does not affect the limits. No full cursor path is saved.

**Movement outside recorded areas:** continuous time in empty/unrecorded areas counts even while the mouse moves between different empty cells. Returning to a recorded area resets that timer. On Balanced, an alert appears after five seconds outside.

**Idle time:** the allowance is `mode_seconds * (1 + 4 * recorded_heat)`, where heat ranges from zero to one. On Balanced this is five seconds in empty space, increasing gradually to 25 seconds at the hottest point. Movement resets the idle timer, including movement that returns to its starting point. Cursor noise within three pixels does not count as meaningful movement. A pause or long sampling interruption starts fresh timers.

## Simple controls

- **Paused / Training / Protection on / Checking activity:** current state.
- **Saved behavior:** whether typing and mouse training are ready.
- **Duration:** how long the training session runs.
- **Alert timing:** Low / Balanced / High select 2.5 / 5 / 7.5 seconds for timed checks.
- **Mouse speed:** average speed while moving, in pixels per second.
- **Typing speed:** physical key presses per second, shown on Overview, Training and Alerts & history.
- **Key hold time:** average press-to-release time, in milliseconds.
- **Time near screen edges:** percentage of recently sampled time near an edge.

## Saving and errors

The original profile stays in `data/profile.json`; additional profiles are in `data/profiles/`. They store measurements, the learning timer, approved cursor areas, saved mouse maps, and a salted password hash. Existing measurements and password hashes are preserved. No typed text or saved list of key identities is stored. Practice text is cleared when paused.

Models are prepared in the background to keep the interface responsive. If a tracking or training callback fails, the app pauses and reports the error instead of silently stopping its timer. Details are written to `data/errors.log`; fatal Python errors are recorded in `data/fatal-errors.log`. The next timer callback still runs so the interface can recover.

An abrupt crash can lose up to the last five seconds since the most recent automatic save. Normal close saves immediately. Profiles are not encrypted; any backup or synchronization of the folder depends on your Windows setup.

## Setup and tests

Requires Windows, Python with Tkinter, and the packages in `requirements.txt`. No extra packages were added for these changes.

```powershell
python -m pip install --target .packages -r requirements.txt
python -m unittest discover -v
```

Tests use simulated input, temporary profiles, and a controllable clock. The Windows lock action is replaced with a test substitute. Coverage includes raw key-mashing traces, rolling typing speed, speed-only alerts and graph lines, both mouse modes, fresh timers after typing, training, saved maps, the grace period, lock errors, compact-window layouts and dialogs. Running tests does not lock the real PC or change your profiles.

Internally, a local Isolation Forest model checks typing rhythm. A separate speed check uses the profile's measured typing-rate distribution, with a range that allows normal variation. Key holds use the explicit twice-the-maximum rule; mouse protection uses peak speed and the separate recorded-area/idle rules. Two-second summaries supply training samples. Typing speed needs at least one second of measurement and two presses; its rolling window continues across summary boundaries. At least five active samples per input type are needed to fit a model. Polling is approximately every 25 ms and can miss shorter presses. Mode delays, speed ranges, heat allowances and model scores are prototype rules, not measured identity accuracy.

## Logo

The app and loading window use the simple, text-free mint shield in `assets/shield.png`, also used as the window icon. The displayed app name is **Behavioral Guard**. The existing **Start BehaviorGuard.cmd** filename is kept so existing shortcuts still work.
