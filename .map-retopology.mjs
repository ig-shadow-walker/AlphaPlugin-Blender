export const meta = {
  name: 'map-smart-retopology',
  description: 'Map the platform Smart Retopology flow (API contract, quality options, 3D source-file upload) for the Blender plugin',
  phases: [{ title: 'Map' }],
}

phase('Map')

const FE = '/Users/aryanbehzadi/Desktop/Projects/Alpha3D/Alpha-2-Frontend'
const BE = '/Users/aryanbehzadi/Desktop/Projects/Alpha3D/Alpha3D-Backend'
const SEED = 'Repos: FRONTEND = ' + FE + ' (React/TanStack; route /smart-retopology, label "Smart Topology"; gen3d API helpers in src/apiOps/gen3dApi.ts; the GenerationBox or a dedicated component drives it), BACKEND = ' + BE + ' (NestJS, no global route prefix; alpha-5 / Hunyuan retopology lives under src/alpha5). generationType for this op is "alpha-5-retopology". Read the ACTUAL current code and cite file:line for EVERY claim. Do not guess param names or values.'

const API_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    generationTypeValue: { type: 'string', description: 'Exact generationType string, with file:line' },
    requiredFields: { type: 'array', description: 'Fields the backend REQUIRES for alpha-5-retopology', items: { type: 'object', additionalProperties: false, properties: { name: { type: 'string' }, type: { type: 'string' }, allowedValues: { type: 'string' }, meaning: { type: 'string' }, fileRef: { type: 'string' } }, required: ['name', 'meaning', 'fileRef'] } },
    qualityParam: { type: 'string', description: 'The topology TARGET / quality control: exact param name(s) (faceLevel? octreeResolution? topologyVCount? faceCount?), their allowed values and what each means, the default, and how they interact (which wins). With file:line in the backend submit path.' },
    file3dType: { type: 'string', description: 'How file3dType (GLB/OBJ/FBX) is required/derived for retopology; what happens if modelUrl is a bare Spaces key vs has an extension. file:line.' },
    modelUrlField: { type: 'string', description: 'How the source mesh is passed (modelUrl: Spaces key vs HTTPS URL), size limit, and whether inline base64 is allowed (it should NOT be for meshes). file:line.' },
    optionalFields: { type: 'array', items: { type: 'object', additionalProperties: false, properties: { name: { type: 'string' }, meaning: { type: 'string' }, fileRef: { type: 'string' } }, required: ['name', 'meaning'] } },
    creditCost: { type: 'string', description: 'Credit cost of a retopology job + file:line' },
    notes: { type: 'string' },
  },
  required: ['generationTypeValue', 'requiredFields', 'qualityParam', 'file3dType', 'modelUrlField', 'creditCost', 'notes'],
}

const UI_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    componentFile: { type: 'string', description: 'The route + component(s) that implement Smart Retopology on the platform. file paths.' },
    sourceInput: { type: 'string', description: 'How the user provides the source mesh: upload a file from disk? pick an existing generation/post? drag a workflow node? ALL that apply, with file:line.' },
    qualityUI: { type: 'string', description: 'The exact quality/target options shown to the user (labels + helper text) and how each maps to the API param(s) from the API agent. With file:line.' },
    hasPreviewGate: { type: 'boolean', description: 'Is there any preview/confirm step, or does it submit straight to retopo on click?' },
    flowSteps: { type: 'array', items: { type: 'string' }, description: 'Ordered user-facing steps from picking a mesh to a finished retopologized model' },
    pollingAndOutput: { type: 'string', description: 'How it polls for completion and where the resulting retopologized mesh URL lives (objFiles.glb? other?). file:line.' },
    notes: { type: 'string' },
  },
  required: ['componentFile', 'sourceInput', 'qualityUI', 'hasPreviewGate', 'flowSteps', 'pollingAndOutput', 'notes'],
}

const UPLOAD_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    presignEndpoint: { type: 'string', description: 'The endpoint used to get a presigned PUT URL for a SOURCE 3D MODEL (mesh, not image) for retopology: method, exact path, request body fields, response fields (uploadUrl + the key/fileName to later send as modelUrl). With file:line. If retopology reuses the image presign endpoint, say so explicitly; if there is a dedicated 3D/model upload endpoint, give it.' },
    putSemantics: { type: 'string', description: 'How the bytes are PUT to the presigned URL: content-type header(s), any x-amz-acl, whether an Authorization header must be ABSENT, success criteria. file:line.' },
    keyToModelUrl: { type: 'string', description: 'How the returned key/fileName is then passed into createGen3DPost as modelUrl (and whether file3dType is sent alongside). file:line.' },
    sizeAndFormats: { type: 'string', description: 'Max file size and accepted formats (GLB/OBJ/FBX/glTF) for the source mesh. file:line.' },
    notes: { type: 'string' },
  },
  required: ['presignEndpoint', 'putSemantics', 'keyToModelUrl', 'sizeAndFormats', 'notes'],
}

const API_TASK = SEED + '\n\nTASK: Map the alpha-5-retopology API CONTRACT exactly. In the backend alpha5 submit path for generationType "alpha-5-retopology" (search alpha5.service.ts / hunyuan.service.ts), find every required and optional field, the topology TARGET/quality param(s) and their allowed values + default + precedence (faceLevel vs octreeResolution vs topologyVCount vs faceCount), how file3dType is required/derived, how the source mesh is passed (modelUrl key/URL, size limit, NO inline base64 for meshes), and the credit cost. Cross-check the frontend CreateGen3DPostRequest fields it actually sends. Cite file:line for everything.'

const UI_TASK = SEED + '\n\nTASK: Map the Smart Retopology UI FLOW on the platform. Find the /smart-retopology route + component(s). Document how the user supplies the SOURCE mesh (upload a file from disk, and/or pick an existing post/generation), the exact quality/target options shown (labels, helper text) and how they map to the API param(s), whether there is any preview/confirm step or it submits on click, the full ordered flow, and how it polls + where the resulting retopologized mesh URL is read. Cite file:line.'

const UPLOAD_TASK = SEED + '\n\nTASK: Map the SOURCE 3D-MODEL UPLOAD mechanism used to get a mesh onto Spaces for retopology. Find the presign endpoint for a model/mesh file (method, path, request, response with the key to send as modelUrl), the exact PUT semantics (content-type, x-amz-acl, no Authorization header), how the returned key becomes modelUrl in createGen3DPost, and the max size + accepted formats (GLB/OBJ/FBX). If retopology reuses the image-to-3d presign endpoint vs a dedicated model-upload endpoint, state which, with file:line.'

const [api, ui, upload] = await parallel([
  () => agent(API_TASK, { label: 'map:retopo-api', schema: API_SCHEMA }),
  () => agent(UI_TASK, { label: 'map:retopo-ui', schema: UI_SCHEMA }),
  () => agent(UPLOAD_TASK, { label: 'map:retopo-upload', schema: UPLOAD_SCHEMA }),
])

return { api, ui, upload }
