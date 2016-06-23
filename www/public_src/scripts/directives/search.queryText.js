angular.module('aiddataDET')
.directive('queryText', function($window) {
  return {
    restrict: "E",
    controller: "QueryTextCtrl",
    scope: {},
    link: function(scope, element, attrs) { },
    templateUrl: "views/components/search.queryText.html"
  };
});
