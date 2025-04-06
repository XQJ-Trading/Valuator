document.addEventListener("DOMContentLoaded", function() {
  // Process each <pre class="output"> element
  const outputElements = document.querySelectorAll("pre.output");
  outputElements.forEach(function(el) {
    // Get the raw text from the element
    const text = el.textContent;
    // Use a regex to extract the content field (e.g., content='...') 
    const regex = /content\s*=\s*(['"])(.*?)\1/;
    const match = regex.exec(text);
    if (match && match[2]) {
      let content = match[2];
      // Replace literal "\n" (backslash + n) with <br>
      content = content.replace(/\\n/g, "<br>");
      // Also replace any actual newline characters with <br>
      content = content.replace(/\n/g, "<br>");
      // Simple markdown formatting: convert **bold** to <strong> and _italic_ to <em>
      content = content.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
      content = content.replace(/_(.*?)_/g, "<em>$1</em>");
      // Additional formatting can be added here as needed (e.g., for LaTeX formulas)
      
      // Update the element's inner HTML with the formatted content
      el.innerHTML = content;
    }
  });
});

// Toggle function to show/hide sections
function toggleSection(id) {
  const section = document.getElementById(id);
  if (!section) return;
  // If the section is not visible or has no inline display set, show it; otherwise, hide it.
  if (section.style.display === "none" || section.style.display === "") {
    section.style.display = "block";
  } else {
    section.style.display = "none";
  }
}