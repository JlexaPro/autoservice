(function(){
  const board = document.getElementById('planner-board');
  if(!board) return;
  const stepMin = Number(board.dataset.stepMin || 30);
  const day = board.dataset.day;
  const startTime = board.dataset.startTime || '09:00';

  function roundToStep(min){ return Math.max(0, Math.round(min/stepMin)*stepMin); }
  function minToTime(min){
    const [h,m]=startTime.split(':').map(Number);
    const total = h*60+m+min;
    const hh = String(Math.floor(total/60)).padStart(2,'0');
    const mm = String(total%60).padStart(2,'0');
    return `${hh}:${mm}`;
  }

  async function updateVisit(block, newTop, newHeight, bayId){
    const visitId = block.dataset.visitId;
    const startMin = roundToStep(newTop/2);
    const endMin = roundToStep((newTop+newHeight)/2);
    const payload = { day, start_time:minToTime(startMin), end_time:minToTime(endMin), service_bay_id:Number(bayId), employee_id:block.dataset.employeeId || null };
    try {
      const res = await fetch(`/service_visits/${visitId}`, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
      if(!res.ok){ const t = await res.text(); alert('Ошибка пересечения/сохранения: '+t); return false; }
      return true;
    } catch(e){ alert('Ошибка сети: '+e); return false; }
  }

  board.querySelectorAll('.visit-block').forEach(block=>{
    block.addEventListener('dblclick', ()=> window.location.href = `/service_visits/${block.dataset.visitId}`);

    let drag = null;
    block.addEventListener('mousedown', (e)=>{
      if(e.target.classList.contains('resize-handle')) return;
      drag = {startY:e.clientY, startX:e.clientX, startTop:parseInt(block.style.top||'0',10), startHeight:parseInt(block.style.height||'60',10), originCol:block.closest('.bay-col')};
      block.style.opacity='0.8';
      document.onmousemove = (ev)=>{
        const dy = ev.clientY-drag.startY;
        block.style.top = `${Math.max(0, drag.startTop + dy)}px`;
        const col = document.elementFromPoint(ev.clientX, ev.clientY)?.closest('.bay-col');
        if(col && col!==block.closest('.bay-col')) col.querySelector('.bay-grid').appendChild(block);
      };
      document.onmouseup = async ()=>{
        document.onmousemove = null; document.onmouseup = null; block.style.opacity='1';
        const col = block.closest('.bay-col');
        const ok = await updateVisit(block, parseInt(block.style.top,10), parseInt(block.style.height,10), col.dataset.bayId);
        if(ok) window.location.reload();
      };
    });

    const handle = block.querySelector('.resize-handle');
    handle?.addEventListener('mousedown', (e)=>{
      e.stopPropagation();
      const rs = {startY:e.clientY, startHeight:parseInt(block.style.height||'60',10)};
      document.onmousemove = (ev)=>{
        const dy = ev.clientY-rs.startY;
        block.style.height = `${Math.max(stepMin*2, rs.startHeight + dy)}px`;
      };
      document.onmouseup = async ()=>{
        document.onmousemove = null; document.onmouseup = null;
        const col = block.closest('.bay-col');
        const ok = await updateVisit(block, parseInt(block.style.top,10), parseInt(block.style.height,10), col.dataset.bayId);
        if(ok) window.location.reload();
      };
    });
  });

  board.querySelectorAll('.bay-grid').forEach(grid=>{
    grid.addEventListener('dblclick',(e)=>{
      if(e.target.closest('.visit-block')) return;
      const y = e.offsetY;
      const min = roundToStep(y/2);
      const start = minToTime(min);
      const end = minToTime(min+stepMin);
      const bay = grid.closest('.bay-col').dataset.bayId;
      const form = document.querySelector('form[action="/service_visits"]');
      if(form){ form.querySelector('[name="start_time"]').value=start; form.querySelector('[name="end_time"]').value=end; form.querySelector('[name="service_bay_id"]').value=bay; window.scrollTo({top:form.offsetTop-20, behavior:'smooth'}); }
    });
  });
})();
