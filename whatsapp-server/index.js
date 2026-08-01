const fs = require('fs');
const path = require('path');
const express = require('express');
const cors = require('cors');
const qrcodeTerminal = require('qrcode-terminal');
const QRCode = require('qrcode');
const { Client, LocalAuth } = require('whatsapp-web.js');

const app = express();
app.use(express.json());
app.use(cors());

const PORT = process.env.PORT || 3001;

let clientStatus = 'initializing';
let authenticated = false;
let latestQrDataUrl = null;

const client = new Client({
    authStrategy: new LocalAuth({ dataPath: './.wwebjs_auth' }),
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    puppeteer: {
        headless: true,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-accelerated-2d-canvas',
            '--no-first-run',
            '--no-zygote',
            '--disable-gpu'
        ]
    }
});

client.on('qr', async (qr) => {
    clientStatus = 'qr_required';
    authenticated = false;
    try {
        latestQrDataUrl = await QRCode.toDataURL(qr);
    } catch (e) {
        console.error('Error generating QR data URL:', e);
    }
    console.log('\n==================================================');
    console.log('NEW QR CODE GENERATED! Open http://127.0.0.1:3001/qr in your browser or scan below:');
    console.log('==================================================\n');
    qrcodeTerminal.generate(qr, { small: true });
    console.log('\nWhatsApp > Linked Devices > Link a Device\n');
});

client.on('authenticated', () => {
    console.log('✅ WhatsApp authenticated successfully!');
    authenticated = true;
    latestQrDataUrl = null;
});

client.on('ready', () => {
    clientStatus = 'ready';
    authenticated = true;
    latestQrDataUrl = null;
    console.log('🚀 WhatsApp Gateway Client is READY! Automatic sending active.');
});

client.on('auth_failure', (msg) => {
    clientStatus = 'auth_failure';
    authenticated = false;
    latestQrDataUrl = null;
    console.error('❌ WhatsApp Auth failure:', msg);
});

client.on('disconnected', (reason) => {
    clientStatus = 'disconnected';
    authenticated = false;
    latestQrDataUrl = null;
    console.log('⚠️ WhatsApp client disconnected:', reason);
    client.initialize();
});

// Endpoint: Visual Web Page to scan QR code cleanly
app.get('/qr', (req, res) => {
    if (clientStatus === 'ready') {
        return res.send(`
            <!DOCTYPE html>
            <html>
            <head><title>WhatsApp Gateway Status</title></head>
            <body style="font-family: sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; background: #f8fafc; margin: 0;">
                <div style="background: white; padding: 2.5rem; border-radius: 1.5rem; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1); text-align: center; max-width: 450px;">
                    <h2 style="color: #059669; margin-top: 0;">✅ WhatsApp Gateway Connected!</h2>
                    <p style="color: #475569; font-size: 0.95rem; margin-bottom: 2rem;">Device is currently linked and sending automated messages.</p>
                    <form action="/reset" method="POST">
                        <button type="submit" style="background: #ef4444; color: white; border: none; padding: 0.75rem 1.5rem; font-weight: bold; border-radius: 0.75rem; cursor: pointer; font-size: 0.9rem;">
                            🔄 Unlink & Link a Different Phone Number
                        </button>
                    </form>
                </div>
            </body>
            </html>
        `);
    }

    if (!latestQrDataUrl) {
        return res.send(`
            <!DOCTYPE html>
            <html>
            <head><title>WhatsApp Gateway QR</title><meta http-equiv="refresh" content="3"></head>
            <body style="font-family: sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; background: #f8fafc;">
                <div style="background: white; padding: 2rem; border-radius: 1rem; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); text-align: center;">
                    <h2>⌛ Generating WhatsApp QR Code...</h2>
                    <p>Please wait 3 seconds. Page will auto-refresh.</p>
                </div>
            </body>
            </html>
        `);
    }

    res.send(`
        <!DOCTYPE html>
        <html>
        <head>
            <title>Scan WhatsApp QR Code</title>
            <meta http-equiv="refresh" content="15">
        </head>
        <body style="font-family: sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; background: #f8fafc; margin: 0;">
            <div style="background: white; padding: 2.5rem; border-radius: 1.5rem; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1); text-align: center; max-width: 400px;">
                <h2 style="color: #0f172a; margin-top: 0;">Link WhatsApp Device</h2>
                <p style="color: #64748b; font-size: 0.9rem; margin-bottom: 1.5rem;">
                    1. Open WhatsApp on your phone<br>
                    2. Go to <strong>Settings &gt; Linked Devices &gt; Link a Device</strong><br>
                    3. Point your camera at the QR code below:
                </p>
                <div style="padding: 1rem; border: 2px dashed #cbd5e1; border-radius: 1rem; display: inline-block; background: #fff;">
                    <img src="${latestQrDataUrl}" style="width: 250px; height: 250px; display: block;" alt="WhatsApp QR Code">
                </div>
                <p style="color: #94a3b8; font-size: 0.75rem; margin-top: 1rem;">QR Code refreshes automatically every 15s</p>
            </div>
        </body>
        </html>
    `);
});

// Endpoint: Check Gateway status
app.get('/status', (req, res) => {
    res.json({
        status: clientStatus,
        authenticated: authenticated,
        ready: clientStatus === 'ready'
    });
});

// Endpoint: Reset session & generate new QR code for a different phone number
app.post('/reset', async (req, res) => {
    console.log('Resetting WhatsApp Gateway session for new phone number...');
    try {
        await client.logout();
    } catch(e) {}
    try {
        await client.destroy();
    } catch(e) {}
    try {
        const authPath = path.join(__dirname, '.wwebjs_auth');
        if (fs.existsSync(authPath)) {
            fs.rmSync(authPath, { recursive: true, force: true });
        }
    } catch(e) {}
    clientStatus = 'qr_required';
    authenticated = false;
    latestQrDataUrl = null;
    client.initialize();
    res.redirect('/qr');
});

// Endpoint: Send WhatsApp message automatically in background
app.post('/send', async (req, res) => {
    const { phone, message } = req.body;

    if (!phone || !message) {
        return res.status(400).json({ success: false, error: 'Phone and message are required.' });
    }

    if (clientStatus !== 'ready') {
        return res.status(503).json({
            success: false,
            error: `WhatsApp Gateway is not ready (status: ${clientStatus}). Scan QR code first at http://127.0.0.1:3001/qr`
        });
    }

    try {
        let cleanPhone = phone.toString().replace(/\D/g, '');

        if (cleanPhone.startsWith('00')) {
            cleanPhone = cleanPhone.substring(2);
        } else if (cleanPhone.startsWith('0') && (cleanPhone.length === 9 || cleanPhone.length === 10)) {
            cleanPhone = '213' + cleanPhone.substring(1);
        }

        const chatId = `${cleanPhone}@c.us`;

        console.log(`Sending message to ${chatId}...`);
        try {
            await client.sendMessage(chatId, message);
            console.log(`✅ Message sent to ${chatId}`);
            return res.json({ success: true, message: `Message sent automatically to ${cleanPhone}` });
        } catch (initialErr) {
            console.warn(`Initial sendMessage to ${chatId} failed (${initialErr.message}), retrying once...`);
            await new Promise(r => setTimeout(r, 1000));
            await client.sendMessage(chatId, message);
            console.log(`✅ Message sent to ${chatId} on retry`);
            return res.json({ success: true, message: `Message sent automatically to ${cleanPhone}` });
        }
    } catch (err) {
        console.error('Failed to send WhatsApp message:', err);
        res.status(500).json({ success: false, error: err.message || 'Failed to send message' });
    }
});

client.initialize();

app.listen(PORT, () => {
    console.log(`WhatsApp Gateway Service listening on http://127.0.0.1:${PORT}`);
    console.log(`QR Web Page available at: http://127.0.0.1:${PORT}/qr`);
});
