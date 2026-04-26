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
    return `${String(Math.floor(total/60)).padStart(2,'0')}:${String(total%60).padStart(2,'0')}`;
  }
  function parseTimeToMin(t){ const [h,m]=String(t).split(':').map(Number); return h*60+m; }

  function hasFrontendCollision(moving, bayId, topPx, heightPx){
    const start = roundToStep(topPx/2);
    const end = roundToStep((topPx+heightPx)/2);
    const cards = board.querySelectorAll(`.bay-col[data-bay-id="${bayId}"] .visit-card`);
    for(const card of cards){
      if(card === moving) continue;
      const cStart = roundToStep(parseInt(card.style.top,10)/2);
      const cEnd = roundToStep((parseInt(card.style.top,10)+parseInt(card.style.height,10))/2);
      if(start < cEnd && end > cStart) return true;
    }
    return false;
  }

  function saveState(card){
    return {
      parent: card.parentElement,
      top: card.style.top,
      height: card.style.height,
      bayId: card.closest('.bay-col')?.dataset.bayId
    };
  }
  function restoreState(card, state){
    state.parent.appendChild(card);
    card.style.top = state.top;
    card.style.height = state.height;
    card.dataset.bayId = state.bayId;
  }

  async function apiUpdate(card){
    const topPx = parseInt(card.style.top,10);
    const hPx = parseInt(card.style.height,10);
    const payload = {
      day,
      start_time: minToTime(roundToStep(topPx/2)),
      end_time: minToTime(roundToStep((topPx+hPx)/2)),
      service_bay_id: Number(card.closest('.bay-col').dataset.bayId),
      employee_id: card.dataset.employeeId || null
    };
    const res = await fetch(`/api/visits/${card.dataset.visitId}/move`, {method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
    return await res.json();
  }

  function lockSelection(lock){ document.body.style.userSelect = lock ? 'none' : ''; }

  board.querySelectorAll('.visit-card').forEach(card => {
    card.addEventListener('dblclick', ()=> openModal(card));
    card.addEventListener('mousedown', (e)=>{
      if(e.target.classList.contains('resize-handle')) return;
      e.preventDefault();
      lockSelection(true);
      card.classList.add('dragging');
      const state = saveState(card);
      const startY = e.clientY;
      const startTop = parseInt(card.style.top||'0',10);
      document.onmousemove = (ev)=>{
        const dy = ev.clientY - startY;
        card.style.top = `${Math.max(0, startTop + dy)}px`;
        const col = document.elementFromPoint(ev.clientX, ev.clientY)?.closest('.bay-col');
        if(col) col.querySelector('.bay-grid').appendChild(card);
      };
      document.onmouseup = async ()=>{
        document.onmousemove = null; document.onmouseup = null;
        card.classList.remove('dragging');
        lockSelection(false);
        const bayId = card.closest('.bay-col').dataset.bayId;
        if(hasFrontendCollision(card, bayId, parseInt(card.style.top,10), parseInt(card.style.height,10))){
          alert('Слот занят: на это время уже есть запись');
          restoreState(card, state);
          return;
        }
        try {
          const data = await apiUpdate(card);
          if(!data.ok){
            alert(data.error || 'Не удалось сохранить запись');
            restoreState(card, state);
          }
        } catch(err){
          alert('Не удалось сохранить запись');
          restoreState(card, state);
        }
      };
    });

    const handle = card.querySelector('.resize-handle');
    handle?.addEventListener('mousedown', (e)=>{
      e.preventDefault(); e.stopPropagation(); lockSelection(true);
      card.classList.add('dragging');
      const state = saveState(card);
      const startY = e.clientY;
      const startHeight = parseInt(card.style.height||'60',10);
      document.onmousemove = (ev)=>{
        const dy = ev.clientY - startY;
        card.style.height = `${Math.max(stepMin*2, startHeight + dy)}px`;
      };
      document.onmouseup = async ()=>{
        document.onmousemove = null; document.onmouseup = null;
        card.classList.remove('dragging');
        lockSelection(false);
        const bayId = card.closest('.bay-col').dataset.bayId;
        if(hasFrontendCollision(card, bayId, parseInt(card.style.top,10), parseInt(card.style.height,10))){
          alert('Слот занят: на это время уже есть запись');
          restoreState(card, state);
          return;
        }
        try {
          const data = await apiUpdate(card);
          if(!data.ok){ alert(data.error || 'Не удалось сохранить запись'); restoreState(card, state); }
        } catch(err){ alert('Не удалось сохранить запись'); restoreState(card, state); }
      };
    });
  });

  const modal = document.getElementById('visit-modal');
  const form = document.getElementById('visit-edit-form');
  document.getElementById('modal-close')?.addEventListener('click', ()=> modal.classList.add('hidden'));

  function openModal(card){
    modal.classList.remove('hidden');
    const topMin = roundToStep(parseInt(card.style.top,10)/2);
    const endMin = roundToStep((parseInt(card.style.top,10)+parseInt(card.style.height,10))/2);
    form.visit_id.value = card.dataset.visitId;
    form.client.value = card.dataset.client || '';
    form.car.value = card.dataset.car || '';
    form.problem_description.value = card.dataset.problem || '';
    form.visit_status.value = card.dataset.status || 'Записан';
    form.day.value = day;
    form.start_time.value = minToTime(topMin);
    form.end_time.value = minToTime(endMin);
    form.work_type.value = card.dataset.workType || '';
    form.service_bay_id.value = card.closest('.bay-col').dataset.bayId;
    form.employee_id.value = card.dataset.employeeId || '';
  }

  form?.addEventListener('submit', async (e)=>{
    e.preventDefault();
    const visitId = form.visit_id.value;
    const payload = {
      day: form.day.value,
      start_time: form.start_time.value,
      end_time: form.end_time.value,
      service_bay_id: form.service_bay_id.value,
      employee_id: form.employee_id.value || null,
      problem_description: form.problem_description.value,
      visit_status: form.visit_status.value,
      work_type: form.work_type.value,
      service_comment: form.service_comment.value,
    };
    try {
      const res = await fetch(`/api/visits/${visitId}`, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
      const data = await res.json();
      if(!data.ok){ alert(data.error || 'Не удалось сохранить запись'); return; }
      window.location.reload();
    } catch(err){ alert('Не удалось сохранить запись'); }
  });

  board.querySelectorAll('.bay-grid').forEach(grid=>{
    grid.addEventListener('dblclick',(e)=>{
      if(e.target.closest('.visit-card')) return;
      const y = e.offsetY;
      const min = roundToStep(y/2);
      const start = minToTime(min);
      const end = minToTime(min+stepMin);
      const bay = grid.closest('.bay-col').dataset.bayId;
      const createForm = document.querySelector('form[action="/service_visits"]');
      if(createForm){ createForm.querySelector('[name="start_time"]').value=start; createForm.querySelector('[name="end_time"]').value=end; createForm.querySelector('[name="service_bay_id"]').value=bay; window.scrollTo({top:createForm.offsetTop-20, behavior:'smooth'}); }
    });
  });
})();
