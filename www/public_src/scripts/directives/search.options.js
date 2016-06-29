angular.module('aiddataDET')
.directive('detOptions', function($window) {
  return {
    restrict: "E",
    controller: "OptionsCtrl",
    scope: {},
    link: function(scope, element, attrs) { },
    templateUrl: "views/components/search.options.html"
  };
});
