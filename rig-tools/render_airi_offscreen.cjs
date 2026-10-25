// MIT. Isolated visual test using an existing AIRI Pixi/Cubism build and Core.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const {app, BrowserWindow} = require('electron');
const args = process.argv.slice(2);
const value = key => args[args.indexOf(key)+1];
const modelFile=path.resolve(value('--model'));
const coreFile=path.resolve(value('--core-file'));
const rendererRoot=path.resolve(value('--renderer-dir'));
const output=path.resolve(value('--out'));
fs.mkdirSync(output,{recursive:true});
const log=message=>{fs.appendFileSync(path.join(output,'test.log'),message+'\n');process.stderr.write(message+'\n');};
setTimeout(()=>{log('Offscreen render timed out');app.exit(2);},90000).unref();
app.setPath('userData',path.join(output,'electron-profile'));
app.commandLine.appendSwitch('no-first-run');
const assets=path.join(rendererRoot,'assets');
const files=fs.readdirSync(assets);
const bundle=pattern=>files.find(file=>pattern.test(file));
const settings=JSON.parse(fs.readFileSync(modelFile,'utf8'));
const expressions=(settings.FileReferences.Expressions||[]).map(item=>({name:item.Name,values:Object.fromEntries(JSON.parse(fs.readFileSync(path.join(path.dirname(modelFile),item.File),'utf8')).Parameters.map(parameter=>[parameter.Id,parameter.Value]))}));
const configuration={model:path.basename(modelFile),expressions,app:bundle(/^app-[A-Za-z0-9_-]+\.js$/),display:bundle(/^display-[A-Za-z0-9_-]+\.js$/),live2d:bundle(/^cubism4\.es-[A-Za-z0-9_-]+\.js$/)};
const mime=file=>file.endsWith('.js')?'text/javascript':file.endsWith('.json')?'application/json':file.endsWith('.png')?'image/png':file.endsWith('.html')?'text/html':'application/octet-stream';
const server=http.createServer((request,response)=>{
 try{
  const route=decodeURIComponent(new URL(request.url,'http://localhost').pathname);
  if(route==='/config.json'){response.setHeader('Content-Type','application/json');response.end(JSON.stringify(configuration));return;}
  let target;
  if(route==='/core.js')target=coreFile;
  else if(route.startsWith('/airi/'))target=path.join(rendererRoot,route.slice(6));
  else if(route.startsWith('/model/'))target=path.join(path.dirname(modelFile),route.slice(7));
  else if(route==='/')target=path.join(__dirname,'render_airi_offscreen.html');
  else{response.writeHead(404);response.end();return;}
  response.setHeader('Content-Type',mime(target));response.end(fs.readFileSync(target));
 }catch(error){response.writeHead(500);response.end(error.message);}
});
app.whenReady().then(async()=>{
 try{
  log('Electron ready');
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const window=new BrowserWindow({show:false,width:1024,height:1536,backgroundColor:'#00000000',webPreferences:{offscreen:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}});
  window.webContents.on('console-message',(_event,level,message)=>log(`[renderer ${level}] ${message}`));
  window.webContents.on('render-process-gone',(_event,details)=>log(JSON.stringify(details)));
  log('Loading isolated renderer');
  await window.loadURL(`http://127.0.0.1:${server.address().port}/`);
  log('Page loaded; waiting for model');
  await window.webContents.executeJavaScript('window.testReady');
  log('Model ready');
  const results=[];
  for(const [name,flipUV,flipY] of [['original',false,false],['flip-uv',true,false],['flip-xy',false,true],['flip-both',true,true]]){
   const result=await window.webContents.executeJavaScript(`window.renderVariant(${JSON.stringify(name)},${flipUV},${flipY})`);
   const image=path.join(output,name+'.png');fs.writeFileSync(image,Buffer.from(result.png.split(',')[1],'base64'));
   delete result.png;results.push({...result,file:path.basename(image)});
  }
  const poses=[{name:'neutral',values:{}},...expressions,
    {name:'blink-left',values:{ParamEyeLOpen:0}},{name:'blink-right',values:{ParamEyeROpen:0}},
    {name:'mouth-open',values:{ParamMouthOpenY:.8}},{name:'gaze-left',values:{ParamEyeBallX:-1}},
    {name:'gaze-right',values:{ParamEyeBallX:1}},{name:'gaze-up',values:{ParamEyeBallY:1}},
    {name:'gaze-down',values:{ParamEyeBallY:-1}},{name:'head-left',values:{ParamAngleX:-15}},
    {name:'head-right',values:{ParamAngleX:15}},{name:'head-up',values:{ParamAngleY:12}},
    {name:'head-down',values:{ParamAngleY:-12}},{name:'breath',values:{ParamBreath:1}}];
  for(const pose of poses){
   const result=await window.webContents.executeJavaScript(`window.renderPose(${JSON.stringify(pose.name)},${JSON.stringify(pose.values)})`);
   const image=path.join(output,pose.name+'.png');fs.writeFileSync(image,Buffer.from(result.png.split(',')[1],'base64'));
   delete result.png;results.push({...result,file:path.basename(image)});
  }
  fs.writeFileSync(path.join(output,'renderer-report.json'),JSON.stringify({renderer:'Actual AIRI Pixi Live2D + Cubism WebGL, offscreen Electron',results},null,2));
  process.stdout.write(JSON.stringify({ok:true,outputs:results.map(item=>path.join(output,item.file)),results})+'\n');
  window.destroy();server.close();app.quit();
 }catch(error){log(error.stack);server.close();app.exit(1);}
});
