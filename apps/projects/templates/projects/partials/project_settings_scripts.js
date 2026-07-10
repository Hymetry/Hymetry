const copyButton = document.getElementById('copyBtn')
const copyButtonIcon = document.getElementById('copyBtnIcon')
const copyClipboardLabel = document.getElementById('copyClipboardLabel')
const domainLabelPattern = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i
const plusIcon = `
  <svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="currentColor"><path d="M362.31-260Q332-260 311-281q-21-21-21-51.31v-455.38Q290-818 311-839q21-21 51.31-21h335.38Q728-860 749-839q21 21 21 51.31v455.38Q770-302 749-281q-21 21-51.31 21H362.31Zm0-60h335.38q4.62 0 8.46-3.85 3.85-3.84 3.85-8.46v-455.38q0-4.62-3.85-8.46-3.84-3.85-8.46-3.85H362.31q-4.62 0-8.46 3.85-3.85 3.84-3.85 8.46v455.38q0 4.62 3.85 8.46 3.84 3.85 8.46 3.85Zm-140 200Q192-120 171-141q-21-21-21-51.31v-515.38h60v515.38q0 4.62 3.85 8.46 3.84 3.85 8.46 3.85h395.38v60H222.31ZM350-320v-480 480Z" /></svg>`
const checkIcon = `
  <svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="currentColor"><path d="M382-253.85 168.62-467.23 211.38-510 382-339.38 748.62-706l42.76 42.77L382-253.85Z"/></svg>`

function showFieldError(errorElement, message) {
  if (!errorElement) {
    return
  }
  errorElement.textContent = message
  errorElement.classList.remove('hidden')
}

function clearFieldError(errorElement) {
  if (!errorElement) {
    return
  }
  errorElement.textContent = ''
  errorElement.classList.add('hidden')
  errorElement.classList.remove('text-yellow-600')
  errorElement.classList.add('text-red-600')
}

function isValidDomainOrUrl(value) {
  const rawValue = String(value || '').trim()
  if (!rawValue) {
    return false
  }

  try {
    const url = new URL(rawValue.includes('://') ? rawValue : `https://${rawValue}`)
    const hostname = url.hostname.replace(/\.$/, '').toLowerCase()
    const labels = hostname.split('.').filter(Boolean)
    const tld = labels[labels.length - 1] || ''

    return (
      labels.length >= 2 &&
      hostname.length <= 253 &&
      !/^\d+$/.test(hostname.replace(/\./g, '')) &&
      tld.length >= 2 &&
      /[a-z]/i.test(tld) &&
      labels.every((label) => domainLabelPattern.test(label))
    )
  } catch (error) {
    return false
  }
}

const allowedDomainForm = document.getElementById('change-allowed-domain-form')
const allowedDomainInput = document.getElementById('allowed-domain-url')
const allowedDomainError = document.getElementById('allowed-domain-url-error')

document.querySelectorAll('[aria-controls="change-allowed-domain"]').forEach((trigger) => {
  trigger.addEventListener('click', () => clearFieldError(allowedDomainError))
})

if (allowedDomainInput) {
  allowedDomainInput.addEventListener('input', () => clearFieldError(allowedDomainError))
}

if (allowedDomainForm && allowedDomainInput) {
  allowedDomainForm.addEventListener('submit', function (event) {
    clearFieldError(allowedDomainError)
    if (!isValidDomainOrUrl(allowedDomainInput.value)) {
      event.preventDefault()
      showFieldError(allowedDomainError, 'Enter a valid product URL.')
      allowedDomainInput.focus()
    }
  })
}

function setCopyButtonCopiedState() {
  if (!copyButton || !copyButtonIcon || !copyClipboardLabel) {
    return
  }

  copyButton.classList.remove('hover:bg-slate-100')
  copyButton.classList.add('bg-green-600', 'text-white')
  copyClipboardLabel.textContent = 'Copied to clipboard'
  copyButtonIcon.innerHTML = checkIcon
  copyButton.setAttribute('disabled', 'disabled')

  setTimeout(() => {
    copyButton.classList.remove('bg-green-600', 'text-white')
    copyButton.classList.add('hover:bg-slate-100')
    copyClipboardLabel.textContent = 'Copy to clipboard'
    copyButtonIcon.innerHTML = plusIcon
    copyButton.removeAttribute('disabled')
  }, 2000)
}

if (copyButton) {
  copyButton.addEventListener('click', async () => {
    const scriptElement = document.getElementById('script-to-copy')
    const scriptContent = scriptElement ? scriptElement.textContent : ''

    try {
      await navigator.clipboard.writeText(scriptContent)
      setCopyButtonCopiedState()
    } catch (error) {
      console.error('Failed to copy: ', error)

      if (!scriptElement) {
        return
      }

      const range = document.createRange()
      range.selectNodeContents(scriptElement)
      const selection = window.getSelection()
      selection.removeAllRanges()
      selection.addRange(range)

      try {
        document.execCommand('copy')
        selection.removeAllRanges()
        setCopyButtonCopiedState()
      } catch (fallbackError) {
        console.error('Failed to copy: ', fallbackError)
      }
    }
  })
}

const deleteConfirmationInput = document.getElementById('delete-confirmation-input')
const deleteProjectButton = document.getElementById('delete-project-btn')
const deleteErrorMessage = document.getElementById('delete-error-message')
const deleteProjectForm = document.getElementById('delete-project-form')

if (deleteConfirmationInput && deleteProjectButton && deleteProjectForm) {
  deleteConfirmationInput.addEventListener('input', function () {
    const projectName = '{{ project.name|escapejs }}'
    const inputValue = this.value.trim()

    if (inputValue === projectName) {
      deleteProjectButton.disabled = false
      deleteErrorMessage.classList.add('hidden')
      return
    }

    deleteProjectButton.disabled = true
    if (inputValue) {
      deleteErrorMessage.classList.remove('hidden')
    } else {
      deleteErrorMessage.classList.add('hidden')
    }
  })

  deleteProjectButton.addEventListener('click', function () {
    const projectName = '{{ project.name|escapejs }}'
    if (deleteConfirmationInput.value.trim() === projectName) {
      deleteProjectForm.submit()
    }
  })
}

const leaveProjectButton = document.getElementById('leave-project-btn')
const leaveProjectForm = document.getElementById('leave-project-form')

if (leaveProjectButton && leaveProjectForm) {
  leaveProjectButton.addEventListener('click', function () {
    leaveProjectForm.submit()
  })
}

const changeTrackingForm = document.getElementById('change-tracking-form')
const trackingScriptInfo = document.getElementById('tracking-script-info')
const trackingInputs = changeTrackingForm ? changeTrackingForm.querySelectorAll('input[name="tracking_mode"]') : []
const initialTrackingMode = (() => {
  for (let index = 0; index < trackingInputs.length; index += 1) {
    if (trackingInputs[index].checked) {
      return trackingInputs[index].value
    }
  }
  return ''
})()

function getSelectedTrackingMode() {
  for (let index = 0; index < trackingInputs.length; index += 1) {
    if (trackingInputs[index].checked) {
      return trackingInputs[index].value
    }
  }
  return ''
}

function updateTrackingScriptInfoVisibility() {
  if (!trackingScriptInfo) {
    return
  }

  if (getSelectedTrackingMode() && getSelectedTrackingMode() !== initialTrackingMode) {
    trackingScriptInfo.classList.remove('hidden')
  } else {
    trackingScriptInfo.classList.add('hidden')
  }
}

if (changeTrackingForm) {
  for (let index = 0; index < trackingInputs.length; index += 1) {
    trackingInputs[index].addEventListener('change', updateTrackingScriptInfoVisibility)
  }
}

const changeProjectNameForm = document.getElementById('change-project-name-form')
const projectNameInput = changeProjectNameForm ? changeProjectNameForm.querySelector('input[name="name"]') : null
const projectNameError = document.getElementById('change-project-name-error')

function existingProjectNamesForRename() {
  if (!changeProjectNameForm) {
    return []
  }

  try {
    return JSON.parse(changeProjectNameForm.dataset.existingProjectNames || '[]')
      .map((name) => String(name || '').trim().toLowerCase())
      .filter(Boolean)
  } catch (error) {
    return []
  }
}

document.querySelectorAll('[aria-controls="change-project-name"]').forEach((trigger) => {
  trigger.addEventListener('click', () => clearFieldError(projectNameError))
})

if (projectNameInput) {
  projectNameInput.addEventListener('input', () => clearFieldError(projectNameError))
}

if (changeProjectNameForm && projectNameInput) {
  changeProjectNameForm.addEventListener('submit', function (event) {
    event.preventDefault()

    const newName = projectNameInput.value.trim()
    clearFieldError(projectNameError)

    if (!newName) {
      showFieldError(projectNameError, 'Project name cannot be empty.')
      projectNameInput.focus()
      return
    }

    if (existingProjectNamesForRename().includes(newName.toLowerCase())) {
      showFieldError(projectNameError, 'A project with this name already exists in this workspace.')
      projectNameInput.focus()
      return
    }

    fetch(changeProjectNameForm.action, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value,
      },
      body: new URLSearchParams(new FormData(changeProjectNameForm)),
    })
      .then((response) => response.json())
      .then((data) => {
        if (!data.success) {
          showFieldError(projectNameError, data.error || 'Error updating project name.')
          projectNameInput.focus()
          return
        }

        const modal = document.getElementById('change-project-name')
        const closeButton = modal ? modal.querySelector('[data-modal-close]') : null
        if (closeButton) {
          closeButton.dispatchEvent(new Event('click'))
        }

        window.location.reload()
      })
      .catch((error) => {
        console.error('Error updating project name:', error)
      })
  })
}
