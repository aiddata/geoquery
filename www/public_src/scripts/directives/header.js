angular.module('aiddataDET')
.directive('detHeader', function($window) {
  return {
    restrict: "E",
    link: function(scope, element, attrs) {},
    templateUrl: "views/components/header.html"
  };
});
