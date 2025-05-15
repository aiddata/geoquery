angular.module('aiddataDET')
.factory('spinFactory', function() {

  /* Config Options At: http://spin.js.org/ */
  var spinner = new Spinner({
    scale: 2
  });

  return {
    start: function(el) {
      el = el || document.querySelector('body');
      spinner.spin(el);
    },
    stop: function() {
      spinner.stop();
    }
  };
});
