angular.module('aiddataDET')
.filter('capitalize', function() {
  return function(string) {
    return _.chain(string)
        .words()
        .map(function(word) { return _.capitalize(word); })
        .join(' ')
        .value();
  };
});
