// MIT. Read-only compiled AIRI controls parser probe in an isolated hidden renderer.
const { app, BrowserWindow } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');
const args=process.argv.slice(2),arg=n=>args[args.indexOf(n)+1];
const renderer=path.resolve(arg('--renderer')),zip=path.resolve(arg('--zip')),out=path.resolve(arg('--out'));
fs.mkdirSync(out,{recursive:true});app.setPath('userData',path.join(out,'isolated-profile'));
const assets=path.join(renderer,'assets');
const manifest=fs.readdirSync(assets).filter(n=>/^manifest-.*\.js$/.test(n)).find(n=>fs.readFileSync(path.join(assets,n),'utf8').includes('function inspectLive2DModelControls('));
if(!manifest)throw Error('COMPILED_INSPECTOR_NOT_FOUND');
setTimeout(()=>app.exit(2),30000).unref();
const server=http.createServer((req,res)=>{
 try{
  const route=decodeURIComponent(new URL(req.url,'http://127.0.0.1').pathname);
  if(route==='/'){
   res.setHeader('Content-Type','text/html');
   res.end(`<script type="module">window.probe=(async()=>{const mod=await import('/assets/${manifest}');const inspect=Object.values(mod).find(fn=>typeof fn==='function'&&fn.name==='inspectLive2DModelControls');if(!inspect)throw Error('INSPECT_EXPORT_MISSING');const archive=await(await fetch('/model.zip')).blob();const value=await inspect(archive);return{expressions:value.expressions.map(item=>({name:item.name,parameterCount:item.parameters?.length||0})),motions:value.motions.length,archiveBytes:archive.size}})();</script>`);return;
  }
  if(route==='/model.zip'){res.end(fs.readFileSync(zip));return;}
  if(!route.startsWith('/assets/')){res.writeHead(404);res.end();return;}
  const file=path.resolve(assets,route.slice(8));
  if(!file.startsWith(assets+path.sep)){res.writeHead(403);res.end();return;}
  res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':'application/octet-stream');res.end(fs.readFileSync(file));
 }catch(e){res.writeHead(500);res.end(e.name);}
});
app.whenReady().then(async()=>{
 let window;
 try{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  window=new BrowserWindow({show:false,width:400,height:300,webPreferences:{offscreen:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}});
  await window.loadURL(`http://127.0.0.1:${server.address().port}/`);
  const result=await window.webContents.executeJavaScript('window.probe');
  const report={ok:true,scope:'Actual compiled AIRI manifest inspector; separate hidden renderer and profile; no live Pinia/card/profile mutation',manifestBundle:manifest,zipSha256:crypto.createHash('sha256').update(fs.readFileSync(zip)).digest('hex'),...result};
  fs.writeFileSync(path.join(out,'compiled-controls-probe.json'),JSON.stringify(report,null,2));process.stdout.write(JSON.stringify(report)+'\n');
  window.destroy();server.close();app.quit();
 }catch(e){process.stderr.write(e.stack+'\n');window?.destroy();server.close();app.exit(1);}
});
