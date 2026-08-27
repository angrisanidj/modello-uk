import { chromium } from 'playwright';
import { writeFile, readFile } from 'node:fs/promises';

const base = process.env.MODEL_URL || 'http://127.0.0.1:8000/index.html?social_card_build=1';
const browser = await chromium.launch({headless:true});
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
page.on('console', msg => console.log('[browser]', msg.type(), msg.text()));
page.on('pageerror', err => console.error('[pageerror]', err.message));
await page.goto(base, {waitUntil:'domcontentloaded', timeout:120000});
await page.waitForFunction(() => typeof window.socialCardReady === 'function' && window.socialCardReady(), null, {timeout:300000});
const token = await page.evaluate(() => window.socialCardVersionToken());
const outputs = [['landscape','social-card-uk-v2.png'],['instagram','social-card-uk-instagram-v2.png']];
for (const [format,file] of outputs) {
  const dataUrl = await page.evaluate(async f => window.socialCardDataUrl(f), format);
  const base64 = dataUrl.split(',')[1];
  const buf = Buffer.from(base64, 'base64');
  if (buf.length < 10000 || buf.subarray(1,4).toString() !== 'PNG') throw new Error(`Invalid generated PNG: ${file}`);
  await writeFile(file, buf);
  console.log(`generated ${file} from model (${format}) · ${buf.length} bytes`);
}
await browser.close();

for (const file of ['share-x.html','share-threads.html','share-facebook.html','share-linkedin.html','share-telegram.html','share-whatsapp.html','share-instagram.html']) {
  let s = await readFile(file,'utf8');
  s = s.replace(/\?v=[A-Za-z0-9._-]+/g, `?v=${token}`);
  await writeFile(file,s);
}
{
  const file='index.html';
  let s=await readFile(file,'utf8');
  s=s.replace(/(social-card-uk-v2\.png\?v=)[A-Za-z0-9._-]+/g, `$1${token}`);
  s=s.replace(/(social-card-uk-instagram-v2\.png\?v=)[A-Za-z0-9._-]+/g, `$1${token}`);
  await writeFile(file,s);
}
console.log('social card version', token);
