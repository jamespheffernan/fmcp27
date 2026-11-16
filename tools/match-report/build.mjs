import {build} from 'esbuild';
import {fileURLToPath} from 'node:url';
await build({entryPoints:[fileURLToPath(new URL('./src/report.jsx',import.meta.url))],bundle:true,minify:true,format:'iife',outfile:fileURLToPath(new URL('./dist/report.js',import.meta.url)),define:{'process.env.NODE_ENV':'"production"'},legalComments:'inline'});
