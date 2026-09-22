# QuickDL Free Mode

QuickDL now has an administrator-controlled **Free Mode / Guest Downloads** switch.

## When Free Mode is ON

- Sign in and Sign up are disabled.
- Google Sign-In is not loaded or used.
- Credits are disabled; users are treated as unlimited guests.
- The monthly 50-credit system is bypassed.
- PayPal checkout is disabled.
- PayPal and Google external SDKs are not loaded by the frontend.
- Video/audio downloads cost 0 credits.
- The downloader still uses the server's normal downloader engine (yt-dlp/ffmpeg where configured); it does not call a payment/auth API.
- Users can download as guests.
- WhatsApp support is shown at the bottom of the public site.

## How the admin controls it

Open `/admin18`, go to **Settings**, and use:

**🟢 Free Mode / Guest Downloads**

ON = free guest mode.
OFF = the normal account/credit/payment system is available according to its individual switches.

The setting is stored in the existing `admin_settings` table, so no new database service is required.

## Important

Free Mode is an application switch, not a replacement for the downloader itself. Sites can still rate-limit or block automated downloads, and platform terms/copyright rules still apply.
