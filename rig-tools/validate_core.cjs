// MIT: validate generated runtime geometry with a user-supplied Cubism Core.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const args = process.argv.slice(2);
const value = name => args[args.indexOf(name) + 1];
const modelFile = path.resolve(value('--model'));
const coreFile = path.resolve(value('--core-file'));
const reportDirectory = args.includes('--report-dir') ? path.resolve(value('--report-dir')) : null;
const directory = path.dirname(modelFile);
const settings = JSON.parse(fs.readFileSync(modelFile, 'utf8'));
const manifest = JSON.parse(fs.readFileSync(path.join(directory, 'build-manifest.json'), 'utf8'));
const originalLog = console.log;
console.log = (...items) => process.stderr.write(items.join(' ') + '\n');
global.require = require;
global.__dirname = path.dirname(coreFile);
vm.runInThisContext(fs.readFileSync(coreFile, 'utf8'), {filename: coreFile});
setTimeout(() => {
  let moc, model;
  try {
    const C = Live2DCubismCore;
    const input = fs.readFileSync(path.join(directory, settings.FileReferences.Moc));
    const buffer = input.buffer.slice(input.byteOffset, input.byteOffset + input.byteLength);
    assert(C.Moc.prototype.hasMocConsistency(buffer), 'MOC consistency failed');
    const corrupted = buffer.slice(0);
    new Uint8Array(corrupted)[0] ^= 255;
    assert.equal(C.Moc.prototype.hasMocConsistency(corrupted), 0, 'Core did not reject corrupted magic');
    moc = C.Moc.fromArrayBuffer(buffer);
    assert(moc, 'fromArrayBuffer failed');
    model = C.Model.fromMoc(moc);
    assert(model, 'Model.fromMoc failed');
    const p = model.parameters, d = model.drawables;
    assert.deepEqual(Array.from(p.ids), manifest.parameters.map(item => item.id), 'Parameter IDs differ');
    assert.deepEqual(Array.from(d.ids), Object.keys(manifest.mesh_dependencies), 'Mesh IDs differ');
    assert.deepEqual(settings.FileReferences.Textures,manifest.textures,'model3 texture references differ from the generated manifest');
    assert.deepEqual((settings.FileReferences.Expressions||[]).map(item=>item.Name),manifest.expressions.map(item=>item.name),'model3 expression definitions differ from the generated manifest');
    for(const textureIndex of d.textureIndices)assert(textureIndex>=0&&textureIndex<settings.FileReferences.Textures.length,'Texture index out of model3 texture range');
    for(const group of settings.Groups||[])if(group.Target==='Parameter')for(const id of group.Ids||[])assert(p.ids.includes(id),`Unknown model3 group parameter: ${id}`);
    for(const area of settings.HitAreas||[])assert(d.ids.includes(area.Id),`Unknown HitArea drawable: ${area.Id}`);
    for(const expression of settings.FileReferences.Expressions||[]){
      const payload=JSON.parse(fs.readFileSync(path.join(directory,expression.File),'utf8'));
      for(const parameter of payload.Parameters||[]){
        assert(p.ids.includes(parameter.Id),`Unknown expression parameter: ${expression.Name}/${parameter.Id}`);
        assert(Number.isFinite(parameter.Value),`Nonfinite expression value: ${expression.Name}/${parameter.Id}`);
        assert(['Add','Multiply','Overwrite'].includes(parameter.Blend||'Add'),`Unknown expression blend: ${parameter.Blend}`);
      }
    }
    for(const motions of Object.values(settings.FileReferences.Motions||{}))for(const motion of motions){
      const payload=JSON.parse(fs.readFileSync(path.join(directory,motion.File),'utf8'));
      for(const curve of payload.Curves||[])if(curve.Target==='Parameter')assert(p.ids.includes(curve.Id),`Unknown motion parameter: ${curve.Id}`);
    }
    if(settings.FileReferences.Physics){
      const physics=JSON.parse(fs.readFileSync(path.join(directory,settings.FileReferences.Physics),'utf8'));
      for(const group of physics.PhysicsSettings||[]){
        for(const input of group.Input||[])if(input.Source?.Target==='Parameter')assert(p.ids.includes(input.Source.Id),`Unknown physics input: ${input.Source.Id}`);
        for(const output of group.Output||[])if(output.Destination?.Target==='Parameter')assert(p.ids.includes(output.Destination.Id),`Unknown physics output: ${output.Destination.Id}`);
      }
    }
    for(let i=0;i<d.count;i++){
      const [page,x,y]=manifest.atlas_placements[d.ids[i]];
      const png=fs.readFileSync(path.join(directory,manifest.textures[page]));
      assert.equal(png.subarray(1,4).toString(),'PNG','Texture is not an actual PNG');
      const width=png.readUInt32BE(16),height=png.readUInt32BE(20);
      assert(Math.abs(d.vertexUvs[i][0]-x/width)<1e-5,`Atlas U origin mismatch: ${d.ids[i]}`);
      assert(Math.abs(d.vertexUvs[i][1]-(1-y/height))<1e-5,`Atlas V origin mismatch: ${d.ids[i]}`);
    }
    const reset = () => {p.values.set(p.defaultValues); model.update();};
    const set = (id, v) => {const i = p.ids.indexOf(id); assert(i >= 0, `Unknown parameter ${id}`); p.values[i] = v;};
    const snapshot = name => ({name, parameters: Object.fromEntries(p.ids.map((id, i) => [id, p.values[i]])), meshes: d.ids.map((id, i) => ({id, texture: d.textureIndices[i], opacity: d.opacities[i], positions: Array.from(d.vertexPositions[i]), uvs: Array.from(d.vertexUvs[i]), indices: Array.from(d.indices[i]), masks: Array.from(d.masks[i]), multiply: d.multiplyColors ? Array.from(d.multiplyColors.slice(i*4, i*4+4)) : [1,1,1,1]}))});
    const signature = pose => crypto.createHash('sha256').update(JSON.stringify(pose.meshes.map(mesh => [mesh.positions.map(x => Math.round(x*1e6)), Math.round(mesh.opacity*1e6), mesh.multiply]))).digest('hex');
    const meshSignature = mesh => JSON.stringify([mesh.positions.map(x => Math.round(x*1e6)), Math.round(mesh.opacity*1e6), mesh.multiply]);
    let cases = 0, minTriangleArea = Infinity;
    function checkGeometry() {
      model.update();
      for (let i=0; i<d.count; i++) {
        const vertices = d.vertexPositions[i], indices = d.indices[i];
        assert(Array.from(vertices).every(Number.isFinite), `Nonfinite geometry: ${d.ids[i]}`);
        assert(Number.isFinite(d.opacities[i]) && d.opacities[i] >= -1e-4 && d.opacities[i] <= 1.0001, `Invalid opacity: ${d.ids[i]}`);
        for (const index of indices) assert(index >= 0 && index < d.vertexCounts[i], `Index out of range: ${d.ids[i]}`);
        for (let j=0; j<indices.length; j+=3) {
          const a=indices[j]*2,b=indices[j+1]*2,c=indices[j+2]*2;
          const area=(vertices[b]-vertices[a])*(vertices[c+1]-vertices[a+1])-(vertices[b+1]-vertices[a+1])*(vertices[c]-vertices[a]);
          assert(Math.abs(area)>1e-12, `Degenerate triangle: ${d.ids[i]}`);
          minTriangleArea = Math.min(minTriangleArea, Math.abs(area));
        }
      }
      cases++;
    }
    reset();checkGeometry();
    const neutral=snapshot('neutral');
    for(const probe of manifest.expected_probes || []){
      reset();for(const [id,v] of Object.entries(probe.values))set(id,v);checkGeometry();
      for(const mesh of probe.meshes){
        const meshIndex=d.ids.indexOf(mesh.id), actual=d.vertexPositions[meshIndex];
        assert(Math.abs(d.opacities[meshIndex]-mesh.opacity)<2e-4, `Opacity interpolation mismatch: ${probe.name} / ${mesh.id}`);
        mesh.indices.forEach((index,j)=>{
          assert(Math.abs(actual[index*2]-mesh.positions[j][0])<2e-4, `X keyform mapping mismatch: ${probe.name} / ${mesh.id}`);
          assert(Math.abs(actual[index*2+1]-mesh.positions[j][1])<2e-4, `Y keyform mapping mismatch: ${probe.name} / ${mesh.id}`);
        });
      }
    }
    const parameterTests=[];
    for (let i=0;i<p.count;i++) {
      reset();set(p.ids[i],p.minimumValues[i]);checkGeometry();const low=snapshot('low');
      reset();set(p.ids[i],p.maximumValues[i]);checkGeometry();const high=snapshot('high');
      let changed=d.ids.filter((id,j)=>meshSignature(low.meshes[j])!==meshSignature(high.meshes[j]));
      let context='defaults';
      if(!changed.length){
        const contextual = v => {reset();for(let j=0;j<p.count;j++)p.values[j]=(p.minimumValues[j]+p.maximumValues[j])/2;set(p.ids[i],v);checkGeometry();return snapshot('contextual');};
        const a=contextual(p.minimumValues[i]), b=contextual(p.maximumValues[i]);
        changed=d.ids.filter((id,j)=>meshSignature(a.meshes[j])!==meshSignature(b.meshes[j]));context='other-parameters-at-midrange';
      }
      const expected=d.ids.filter(id=>manifest.mesh_dependencies[id].includes(p.ids[i]));
      assert(changed.length, `Parameter ${p.ids[i]} has no actual influence`);
      for(const mesh of changed) assert(expected.includes(mesh), `Parameter ${p.ids[i]} unexpectedly changes ${mesh}`);
      parameterTests.push({id:p.ids[i],changedMeshes:changed,context});
    }
    const poses=[neutral], expressionSignatures=new Map();
    for (const expression of manifest.expressions) {
      reset();for(const [id,v] of Object.entries(expression.values))set(id,v);checkGeometry();
      const pose=snapshot(expression.name), hash=signature(pose);
      assert(!expressionSignatures.has(hash), `Duplicate actual expression: ${expression.name} and ${expressionSignatures.get(hash)}`);
      expressionSignatures.set(hash,expression.name);poses.push(pose);
    }
    for(const [id,v] of [['ParamEyeLOpen',0],['ParamEyeROpen',0],['ParamMouthOpenY',1]]) {
      if(p.ids.includes(id)){reset();set(id,v);checkGeometry();poses.push(snapshot(id));}
    }
    let seed=12345;
    for(let sample=0;sample<40;sample++){
      reset();for(let i=0;i<p.count;i++){seed=(seed*1664525+1013904223)>>>0;p.values[i]=p.minimumValues[i]+(p.maximumValues[i]-p.minimumValues[i])*seed/0xffffffff;}checkGeometry();
    }
    const report={status:'PASS',coreVersion:C.Version.csmGetVersion(),hasMocConsistency:1,invalidMagicRejected:true,fromArrayBuffer:true,modelFromMoc:true,meshes:d.count,parameters:p.count,expressions:manifest.expressions.length,expressionNames:manifest.expressions.map(item=>item.name),geometryCases:cases,minTriangleArea,parameterTests,vertexCounts:Array.from(d.vertexCounts),indexCounts:Array.from(d.indexCounts),maskCounts:Array.from(d.maskCounts),scope:'Actual Core binary/mesh/parameter/combined-expression validation. Visual likeness and target-app rendering need separate review.'};
    if(reportDirectory){
      fs.mkdirSync(reportDirectory,{recursive:true});
      fs.writeFileSync(path.join(reportDirectory,'core-validation.json'),JSON.stringify(report,null,2));
      fs.writeFileSync(path.join(reportDirectory,'core-poses.json'),JSON.stringify({canvas:manifest.canvas,pixels_per_unit:manifest.pixels_per_unit,textures:manifest.textures,poses}));
    }
    process.stdout.write(JSON.stringify(report)+'\n');
  } catch(error) {
    process.stderr.write(error.stack+'\n');process.exitCode=1;
  } finally {
    if(model)model.release();if(moc)moc._release();console.log=originalLog;
  }
},1000);
