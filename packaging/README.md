# LumenGray — How to install and run

LumenGray runs on your own computer. There is **nothing to install** — you
download one file, double-click it, and your web browser opens with the app.
No Python, no terminal, no setup.

---

## Mac

### 1. Download and install

Download **`LumenGray-macos.dmg`** from the
[latest release](https://github.com/rsiegemit/LumenGray/releases/latest) and
double-click it. A window opens showing the **LumenGray** app and an
**Applications** folder — drag **LumenGray** onto **Applications** to install it.
(Prefer no installer? A **`LumenGray-macos.zip`** of the raw app is on the same
release; double-click to unzip and use the app directly.)

### 2. Open it the first time (important)

Because this app isn't from the Mac App Store, macOS will be cautious the very
first time you open it. This is normal. Do this **once**:

1. **Right-click** (or hold **Control** and click) the **LumenGray** icon.
2. Choose **Open** from the menu.
3. A box will pop up saying it's from an unidentified developer. Click **Open**.

After that first time, you can open it normally with a regular double-click.

> If you double-click first and macOS says it "cannot be opened," don't worry —
> just follow the right-click → **Open** steps above and it will work.
>
> On newer macOS versions you may instead need to go to
> **System Settings → Privacy & Security**, scroll down, and click
> **Open Anyway** next to the LumenGray message.

### 3. Use it

A moment after opening, your default web browser opens automatically with
LumenGray ready to use. To stop the app, just quit it (close it from the Dock).

---

## Windows

### 1. Download the installer

Download **`LumenGray-Setup.exe`** from the
[latest release](https://github.com/rsiegemit/LumenGray/releases/latest)
(or use the **Download for Windows** button in the main README).

### 2. Run the installer

Double-click **`LumenGray-Setup.exe`**. It installs for just your account, so it
**won't ask for an administrator password**, and it adds **LumenGray** to your
Start Menu (and a Desktop shortcut if you tick the box).

### 3. Get past the blue "Windows protected your PC" screen (important)

The first time you run it, Windows SmartScreen may show a blue box that says
**"Windows protected your PC."** This is normal for new apps. Do this **once**:

1. Click the small **More info** link in that blue box.
2. A **Run anyway** button appears — click it.

Then launch **LumenGray** from the Start Menu; your default browser opens
automatically with the app ready to use. To remove it later, use
**Settings → Apps** like any other program.

> Prefer no installer? Download the portable **`LumenGray-windows.zip`** instead,
> right-click → **Extract All…**, open the **LumenGray** folder, and run
> **`LumenGray.exe`**. Keep all the files in that folder together.

---

## What happens when you open it

1. LumenGray quietly starts a small local server **on your own computer only**
   (nothing is sent over the internet).
2. Your default browser opens automatically to the LumenGray page.
3. If the usual address is busy, it automatically picks another one — you don't
   have to do anything.

## Troubleshooting

- **The browser didn't open.** Wait a few seconds. If it still doesn't, look at
  the small window/log for a line like `LumenGray -> http://127.0.0.1:8000` and
  type that address into your browser.
- **A page says it can't connect.** Give it a few more seconds after launch, then
  refresh the browser.
- **Nothing happens on Mac.** Use **right-click → Open** (see Mac step 2).
- **To quit:** close/quit the LumenGray app (Mac: quit from the Dock; Windows:
  close the small console window if one is showing).

---

*These apps are unsigned, which is why macOS and Windows ask you to confirm the
first launch. That's expected and safe to allow for this app.*
