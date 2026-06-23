# LumenGray — How to install and run

LumenGray runs on your own computer. There is **nothing to install** — you
download one file, double-click it, and your web browser opens with the app.
No Python, no terminal, no setup.

---

## Mac

### 1. Download

Download **`LumenGray-macos.zip`** and double-click it to unzip. You'll get an
app called **LumenGray**. (Drag it into your **Applications** folder if you like.)

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

### 1. Download

Download **`LumenGray-windows.zip`**, right-click it, and choose
**Extract All…**. Open the extracted **LumenGray** folder.

### 2. Run it

Double-click **`LumenGray.exe`** inside that folder.

### 3. Get past the blue "Windows protected your PC" screen (important)

The first time you run it, Windows SmartScreen may show a blue box that says
**"Windows protected your PC."** This is normal for new apps. Do this **once**:

1. Click the small **More info** link in that blue box.
2. A **Run anyway** button appears — click it.

LumenGray will start, and your default web browser opens automatically with the
app ready to use.

> Tip: keep all the files together in the LumenGray folder. The `.exe` needs the
> other files next to it to run. You can make a desktop shortcut to
> `LumenGray.exe` if you want quick access.

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
