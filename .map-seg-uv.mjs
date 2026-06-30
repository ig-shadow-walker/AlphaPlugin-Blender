export const meta = {
  name: 'map-segmentation-and-uvunwrap',
  description: 'Map the platform AI Segmentation and UV Unwrap flows (API contract, options, staged-vs-oneshot, output) for the Blender plugin',
  phases: [{ title: 'Map' }],
}

phase('Map')

const FE = '/Users/aryanbehzadi/Desktop/Projects/Alpha3D/Alpha-2-Frontend'
const BE = '/Users/aryanbehzadi/Desktop/Projects/Alpha3D/Alpha3D-Backend'
const SEED = 'Repos: FRONTEND = ' + FE + ' (React/TanStack; routes /ai-segmentation and /uv-unwrapping; gen3d API helpers in src/apiOps/gen3dApi.ts), BACKEND = ' + BE + ' (NestJS, no global route prefix; alpha-5 / Hunyuan ops under src/alpha5; submit branches in alpha5.service.ts, Tencent calls in hunyuan.service.ts, poll dispatch in alpha5.service.ts pollJobStatus). Both ops take a SOURCE MESH via modelUrl (same upload-post mechanism retopology uses: POST /gen3d/create generationType:upload -> presigned PUT + key -> modelUrl). Read the ACTUAL current code and cite file:line for EVERY claim. Do not guess param names/values.'

const FEATURE_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    generationTypeValue: { type: 'string', description: 'Exact generationType string(s) for this op (segmentation may have a preview variant). file:line.' },
    requiredFields: { type: 'array', items: { type: 'object', additionalProperties: false, properties: { name: { type: 'string' }, type: { type: 'string' }, meaning: { type: 'string' }, fileRef: { type: 'string' } }, required: ['name', 'meaning', 'fileRef'] } },
    acceptedFormats: { type: 'string', description: 'Which file3dType values are accepted (GLB/OBJ/FBX), whether file3dType is required or derivable from the modelUrl extension (and the bare-key rule), and any rejected formats. file:line.' },
    options: { type: 'array', description: 'Op-specific tuning params (e.g. packMethod for UV unwrap; maxNumParts + staged flags for segmentation)', items: { type: 'object', additionalProperties: false, properties: { name: { type: 'string' }, allowedValues: { type: 'string' }, defaultValue: { type: 'string' }, uiLabel: { type: 'string' }, meaning: { type: 'string' }, fileRef: { type: 'string' } }, required: ['name', 'meaning', 'fileRef'] } },
    isMultiStep: { type: 'boolean', description: 'Does the platform REQUIRE a staged/preview step (e.g. segmentation preview + edit) before the final result, or can a single submit produce a finished result?' },
    multiStepDetail: { type: 'string', description: 'If multi-step: explain the stages AND the MINIMAL one-shot path (what to send to get an auto result WITHOUT manual editing — e.g. omit enableStagedGeneration / set it false). If single-step: say so. With file:line.' },
    creditCost: { type: 'string', description: 'Credit cost + file:line' },
    output: { type: 'string', description: 'Where the RESULT mesh URL lives after completion (objFiles.glb? a parts array? multiple files?), and for segmentation whether parts come back as ONE GLB containing multiple objects or as separate files. file:line.' },
    pollDispatch: { type: 'string', description: 'Confirm pollJobStatus in alpha5.service.ts handles this generationType (which Tencent describe call) so POST /alpha-5/poll/:id works. file:line.' },
    uiFlow: { type: 'string', description: 'The platform route + flow component, how the user supplies the source mesh (upload file + pick existing), the options UI exposed, and the ordered steps. file:line.' },
    notes: { type: 'string' },
  },
  required: ['generationTypeValue', 'requiredFields', 'acceptedFormats', 'options', 'isMultiStep', 'multiStepDetail', 'creditCost', 'output', 'pollDispatch', 'uiFlow', 'notes'],
}

const UV_TASK = SEED + '\n\nTASK: Map the UV UNWRAP op (generationType likely "alpha-5-uv_unwrap"). Find the backend submit branch and Tencent call, every required + optional field, the accepted file3dType formats (does it accept FBX, unlike retopology?), the packMethod option (allowed values none/blender/uvpackmaster? default? UI label) and ANY other tuning params, the credit cost, where the result mesh URL lives after completion, and the platform UI flow at /uv-unwrapping. Confirm pollJobStatus handles uv_unwrap. Cite file:line.'

const SEG_TASK = SEED + '\n\nTASK: Map the AI SEGMENTATION op (generationType "alpha-5-segment"/"alpha-5-segment_preview" or similar — find the exact strings). CRITICAL: determine whether a SINGLE submit can produce a finished auto-segmented result, or whether the staged preview+edit flow (EnableStagedGeneration / PartSegmentationInfo) is MANDATORY — and if staged, what the MINIMAL one-shot path is (what to send to get an auto N-part split WITHOUT manual vertex editing). Map maxNumParts (min/max/default), enableStagedGeneration, partSegmentationInfo, accepted file3dType formats, credit cost, and CRUCIALLY the output: do the segmented parts come back as ONE GLB with multiple objects, or as separate files/a parts array (and where)? Map the platform UI flow at /ai-segmentation. Confirm pollJobStatus handles segmentation. Cite file:line.'

const [uv, seg] = await parallel([
  () => agent(UV_TASK, { label: 'map:uv-unwrap', schema: FEATURE_SCHEMA }),
  () => agent(SEG_TASK, { label: 'map:segmentation', schema: FEATURE_SCHEMA }),
])

return { uv, seg }
