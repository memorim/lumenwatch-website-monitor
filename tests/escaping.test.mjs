import test from 'node:test';
import assert from 'node:assert/strict';
import {escapeHtml} from '../app/static/escape.js';
test('watch names, extracted words and URL attributes remain text',()=>{
 assert.equal(escapeHtml('<img src=x onerror=alert(1)>'), '&lt;img src=x onerror=alert(1)&gt;');
 assert.equal(escapeHtml('https://example.com/" onmouseover="alert(1)'), 'https://example.com/&quot; onmouseover=&quot;alert(1)');
 assert.equal(escapeHtml('R&D'), 'R&amp;D');
});
