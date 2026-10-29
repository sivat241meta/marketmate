/* Customer contact memory (Task 60): prefill the order name/phone from
   this phone's own localStorage and remember them on send. The number
   only leaves the phone with an order the customer sends. */
document.addEventListener("DOMContentLoaded", () => {
  const NAME_KEY = "mm_customer_name";
  const PHONE_KEY = "mm_customer_phone";

  function read(key) {
    try {
      return window.localStorage.getItem(key) || "";
    } catch (err) {
      return "";
    }
  }

  function write(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (err) { /* private mode: prefill just works once */ }
  }

  document.querySelectorAll("[data-customer-name]").forEach((el) => {
    if (!el.value) {
      el.value = read(NAME_KEY);
    }
  });
  document.querySelectorAll("[data-customer-phone]").forEach((el) => {
    if (!el.value) {
      el.value = read(PHONE_KEY);
    }
  });

  function save(root) {
    if (!root || !root.querySelector) {
      return;
    }
    const name = root.querySelector("[data-customer-name]");
    const phone = root.querySelector("[data-customer-phone]");
    if (name && name.value.trim()) {
      write(NAME_KEY, name.value.trim());
    }
    if (phone && phone.value.trim()) {
      write(PHONE_KEY, phone.value.trim());
    }
  }

  document.querySelectorAll("form").forEach((form) => {
    if (form.querySelector("[data-customer-name],[data-customer-phone]")) {
      form.addEventListener("submit", () => save(form));
    }
  });
  // The live voice widget sends over a socket: remember on every change.
  document.querySelectorAll("[data-customer-name],[data-customer-phone]")
    .forEach((el) => {
      el.addEventListener("change", () => save(document));
    });
  // Pages with two copies (desktop summary + sheet, quote method tabs)
  // keep them in sync while typing.
  ["data-customer-name", "data-customer-phone"].forEach((attr) => {
    const fields = Array.from(document.querySelectorAll("[" + attr + "]"));
    fields.forEach((el) => {
      el.addEventListener("input", () => {
        fields.forEach((other) => {
          if (other !== el) {
            other.value = el.value;
          }
        });
      });
    });
  });
  // The cart sheet sends without a form: remember on every Send tap.
  document.querySelectorAll("[data-cart-submit]").forEach((btn) => {
    btn.addEventListener("click", () => save(document));
  });
});
