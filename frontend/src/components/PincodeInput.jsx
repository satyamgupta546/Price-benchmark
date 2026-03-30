import { useState, useEffect, useRef } from 'react'
import { usePincodes } from '../hooks/useScrapeData'

export default function PincodeInput({ pincodes: selectedPincodes, onPincodesChange }) {
  const { pincodes, error: pincodeError, fetchPincodes } = usePincodes()
  const [selectedStates, setSelectedStates] = useState([])
  const [selectedCities, setSelectedCities] = useState([])
  const [stateDropdownOpen, setStateDropdownOpen] = useState(false)
  const [cityDropdownOpen, setCityDropdownOpen] = useState(false)
  const [pincodeDropdownOpen, setPincodeDropdownOpen] = useState(false)
  const [manualInput, setManualInput] = useState('')
  const [stateSearch, setStateSearch] = useState('')
  const [citySearch, setCitySearch] = useState('')
  const [pincodeSearch, setPincodeSearch] = useState('')
  const stateInputRef = useRef(null)
  const cityInputRef = useRef(null)
  const pincodeInputRef = useRef(null)

  useEffect(() => { fetchPincodes() }, [fetchPincodes])

  // Focus search input when dropdown opens
  useEffect(() => { if (stateDropdownOpen) setTimeout(() => stateInputRef.current?.focus(), 50) }, [stateDropdownOpen])
  useEffect(() => { if (cityDropdownOpen) setTimeout(() => cityInputRef.current?.focus(), 50) }, [cityDropdownOpen])
  useEffect(() => { if (pincodeDropdownOpen) setTimeout(() => pincodeInputRef.current?.focus(), 50) }, [pincodeDropdownOpen])

  const states = pincodes ? Object.keys(pincodes).sort() : []
  const filteredStates = stateSearch
    ? states.filter(s => s.toLowerCase().includes(stateSearch.toLowerCase()))
    : states

  const cities = selectedStates.length > 0 && pincodes
    ? selectedStates.flatMap(s => Object.keys(pincodes[s] || {}).map(c => ({ city: c, state: s }))).sort((a, b) => a.city.localeCompare(b.city))
    : []
  const filteredCities = citySearch
    ? cities.filter(c => c.city.toLowerCase().includes(citySearch.toLowerCase()) || c.state.toLowerCase().includes(citySearch.toLowerCase()))
    : cities

  const availablePincodes = selectedCities.length > 0 && pincodes
    ? [...new Set(selectedCities.flatMap(({ city, state }) => (pincodes[state]?.[city] || [])))]
    : []
  const filteredPincodes = pincodeSearch
    ? availablePincodes.filter(p => p.includes(pincodeSearch))
    : availablePincodes

  const toggleState = (state) => {
    setSelectedStates(prev => {
      const next = prev.includes(state) ? prev.filter(s => s !== state) : [...prev, state]
      if (!next.includes(state)) setSelectedCities(prev => prev.filter(c => c.state !== state))
      return next
    })
  }
  const toggleCity = (cityObj) => {
    setSelectedCities(prev => {
      const exists = prev.find(c => c.city === cityObj.city && c.state === cityObj.state)
      return exists ? prev.filter(c => !(c.city === cityObj.city && c.state === cityObj.state)) : [...prev, cityObj]
    })
  }
  const togglePincode = (pin) => {
    onPincodesChange(selectedPincodes.includes(pin) ? selectedPincodes.filter(p => p !== pin) : [...selectedPincodes, pin])
  }
  const selectAllPincodes = () => {
    const target = filteredPincodes.length > 0 ? filteredPincodes : availablePincodes
    const allNew = target.filter(p => !selectedPincodes.includes(p))
    onPincodesChange(allNew.length > 0 ? [...selectedPincodes, ...allNew] : selectedPincodes.filter(p => !target.includes(p)))
  }
  const addManualPincode = (text) => {
    const input = text ?? manualInput
    const pins = (input.match(/\d{6}/g) || []).filter(p => !selectedPincodes.includes(p))
    if (pins.length > 0) {
      onPincodesChange([...selectedPincodes, ...new Set(pins)])
      setManualInput('')
    }
  }
  const closeAll = () => {
    setStateDropdownOpen(false); setCityDropdownOpen(false); setPincodeDropdownOpen(false)
    setStateSearch(''); setCitySearch(''); setPincodeSearch('')
  }

  const btnCls = "w-full rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2.5 text-sm text-gray-900 dark:text-gray-200 text-left flex items-center justify-between hover:border-blue-400 dark:hover:border-purple-500/50 transition-colors"
  const btnDisCls = "disabled:bg-gray-100 dark:disabled:bg-gray-800/50 disabled:text-gray-400 dark:disabled:text-gray-600 disabled:border-gray-200 dark:disabled:border-gray-700/50"
  const ddCls = "absolute z-30 mt-1 w-full bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 shadow-xl max-h-72 overflow-hidden flex flex-col"
  const labelCls = "flex items-center gap-2 px-3 py-2 hover:bg-blue-50 dark:hover:bg-gray-700 cursor-pointer"
  const cbCls = "rounded border-gray-300 dark:border-gray-600 text-blue-600 dark:text-purple-500 bg-white dark:bg-gray-700 focus:ring-blue-500 dark:focus:ring-purple-500"
  const searchCls = "w-full px-3 py-2 text-sm border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-200 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:bg-blue-50/50 dark:focus:bg-gray-700/50"

  return (
    <div className="space-y-4">
      {pincodeError && (
        <div className="flex items-center gap-3 px-4 py-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl">
          <svg className="w-5 h-5 text-red-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" /></svg>
          <div>
            <p className="text-sm font-semibold text-red-700 dark:text-red-300">{pincodeError}</p>
            <p className="text-xs text-red-500 dark:text-red-400 mt-0.5">Auto-retrying every 3 seconds...</p>
          </div>
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {/* State */}
        <div className="relative">
          <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">State</label>
          <button onClick={() => { closeAll(); setStateDropdownOpen(!stateDropdownOpen) }} className={btnCls}>
            <span className={selectedStates.length ? '' : 'text-gray-400 dark:text-gray-500'}>{selectedStates.length ? `${selectedStates.length} selected` : 'Select states'}</span>
            <svg className="w-4 h-4 text-gray-400 dark:text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
          </button>
          {stateDropdownOpen && <div className={ddCls}>
            <input ref={stateInputRef} type="text" placeholder="Type to search states..." value={stateSearch} onChange={e => setStateSearch(e.target.value)} className={searchCls} />
            <div className="overflow-y-auto flex-1">
              {filteredStates.length === 0 && <p className="px-3 py-3 text-sm text-gray-400 dark:text-gray-500">No states match "{stateSearch}"</p>}
              {filteredStates.map(s => (
                <label key={s} className={labelCls}><input type="checkbox" checked={selectedStates.includes(s)} onChange={() => toggleState(s)} className={cbCls} /><span className="text-sm text-gray-700 dark:text-gray-300">{s}</span></label>
              ))}
            </div>
          </div>}
          {selectedStates.length > 0 && <div className="flex flex-wrap gap-1 mt-1.5">{selectedStates.map(s => (
            <span key={s} className="inline-flex items-center gap-1 px-2 py-0.5 bg-blue-100 dark:bg-purple-900/50 text-blue-700 dark:text-purple-300 rounded-full text-xs font-medium border border-transparent dark:border-purple-700/50">
              {s}<button onClick={() => toggleState(s)} className="hover:text-blue-900 dark:hover:text-purple-100">&times;</button>
            </span>
          ))}</div>}
        </div>

        {/* City */}
        <div className="relative">
          <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">City</label>
          <button onClick={() => { closeAll(); setCityDropdownOpen(!cityDropdownOpen) }} disabled={!selectedStates.length} className={`${btnCls} ${btnDisCls}`}>
            <span className={selectedCities.length ? '' : 'text-gray-400 dark:text-gray-500'}>{selectedCities.length ? `${selectedCities.length} selected` : 'Select cities'}</span>
            <svg className="w-4 h-4 text-gray-400 dark:text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
          </button>
          {cityDropdownOpen && cities.length > 0 && <div className={ddCls}>
            <input ref={cityInputRef} type="text" placeholder="Type to search cities..." value={citySearch} onChange={e => setCitySearch(e.target.value)} className={searchCls} />
            <div className="overflow-y-auto flex-1">
              {filteredCities.length === 0 && <p className="px-3 py-3 text-sm text-gray-400 dark:text-gray-500">No cities match "{citySearch}"</p>}
              {filteredCities.map(({ city, state }) => (
                <label key={`${state}-${city}`} className={labelCls}><input type="checkbox" checked={!!selectedCities.find(c => c.city === city && c.state === state)} onChange={() => toggleCity({ city, state })} className={cbCls} /><span className="text-sm text-gray-700 dark:text-gray-300">{city}</span><span className="text-xs text-gray-400 dark:text-gray-500 ml-auto">{state}</span></label>
              ))}
            </div>
          </div>}
          {selectedCities.length > 0 && <div className="flex flex-wrap gap-1 mt-1.5">{selectedCities.map(({ city, state }) => (
            <span key={`${state}-${city}`} className="inline-flex items-center gap-1 px-2 py-0.5 bg-green-100 dark:bg-emerald-900/50 text-green-700 dark:text-emerald-300 rounded-full text-xs font-medium border border-transparent dark:border-emerald-700/50">
              {city}<button onClick={() => toggleCity({ city, state })} className="hover:text-green-900 dark:hover:text-emerald-100">&times;</button>
            </span>
          ))}</div>}
        </div>

        {/* Pincodes */}
        <div className="relative">
          <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">Pincodes</label>
          <button onClick={() => { closeAll(); setPincodeDropdownOpen(!pincodeDropdownOpen) }} disabled={!availablePincodes.length} className={`${btnCls} ${btnDisCls}`}>
            <span className={selectedPincodes.length ? '' : 'text-gray-400 dark:text-gray-500'}>{selectedPincodes.length ? `${selectedPincodes.length} selected` : 'Select pincodes'}</span>
            <svg className="w-4 h-4 text-gray-400 dark:text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
          </button>
          {pincodeDropdownOpen && availablePincodes.length > 0 && <div className={ddCls}>
            <input ref={pincodeInputRef} type="text" placeholder="Type to search pincodes..." value={pincodeSearch} onChange={e => setPincodeSearch(e.target.value.replace(/\D/g, ''))} className={`${searchCls} font-mono`} />
            <button onClick={selectAllPincodes} className="w-full text-left px-3 py-2 text-xs font-semibold text-blue-600 dark:text-purple-400 hover:bg-blue-50 dark:hover:bg-gray-700 border-b border-gray-200 dark:border-gray-700">
              {(filteredPincodes.length > 0 ? filteredPincodes : availablePincodes).every(p => selectedPincodes.includes(p)) ? 'Deselect All' : 'Select All'}
            </button>
            <div className="overflow-y-auto flex-1">
              {filteredPincodes.length === 0 && <p className="px-3 py-3 text-sm text-gray-400 dark:text-gray-500 font-mono">No pincodes match "{pincodeSearch}"</p>}
              {filteredPincodes.map(pin => (
                <label key={pin} className={labelCls}><input type="checkbox" checked={selectedPincodes.includes(pin)} onChange={() => togglePincode(pin)} className={cbCls} /><span className="text-sm text-gray-700 dark:text-gray-300 font-mono">{pin}</span></label>
              ))}
            </div>
          </div>}
        </div>

        {/* Manual */}
        <div>
          <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">Add Pincode</label>
          <div className="flex gap-2">
            <input type="text" value={manualInput}
              onChange={e => setManualInput(e.target.value.replace(/[^\d,\s]/g, ''))}
              onKeyDown={e => e.key === 'Enter' && addManualPincode()}
              onPaste={e => { e.preventDefault(); const t = e.clipboardData.getData('text'); const pins = (t.match(/\d{6}/g) || []).filter(p => !selectedPincodes.includes(p)); if (pins.length > 0) { onPincodesChange([...selectedPincodes, ...new Set(pins)]); setManualInput(''); } else { setManualInput(t.replace(/[^\d,\s]/g, '')); } }}
              placeholder="e.g. 800001, 110001, 560001"
              className="flex-1 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2.5 text-sm text-gray-900 dark:text-gray-200 font-mono focus:ring-2 focus:ring-blue-500 dark:focus:ring-purple-500 focus:border-blue-500 dark:focus:border-purple-500 placeholder-gray-400 dark:placeholder-gray-500" />
            <button onClick={() => addManualPincode()} disabled={!(manualInput.match(/\d{6}/g) || []).length}
              className="px-3.5 py-2.5 bg-blue-600 dark:bg-purple-600 text-white rounded-lg text-sm font-bold disabled:opacity-30 hover:bg-blue-700 dark:hover:bg-purple-500 transition-colors">+</button>
          </div>
        </div>
      </div>

      {selectedPincodes.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs font-semibold text-gray-500 uppercase mr-1">Pincodes:</span>
          {selectedPincodes.map(pin => (
            <span key={pin} className="inline-flex items-center gap-1 px-2.5 py-1 bg-blue-100 dark:bg-indigo-900/50 text-blue-700 dark:text-indigo-300 rounded-lg text-xs font-mono font-semibold border border-transparent dark:border-indigo-700/50">
              {pin}<button onClick={() => onPincodesChange(selectedPincodes.filter(p => p !== pin))} className="hover:text-blue-900 dark:hover:text-indigo-100 ml-0.5">&times;</button>
            </span>
          ))}
          {selectedPincodes.length > 1 && <button onClick={() => onPincodesChange([])} className="text-xs text-red-500 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300 ml-2">Clear all</button>}
        </div>
      )}

      {(stateDropdownOpen || cityDropdownOpen || pincodeDropdownOpen) && <div className="fixed inset-0 z-20" onClick={closeAll} />}
    </div>
  )
}
