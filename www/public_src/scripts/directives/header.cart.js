angular.module('aiddataDET')
.directive('headerCart', function($window) {
  return {
    restrict: "E",
    link: function(scope, element, attrs) {},
    templateUrl: "views/components/header.cart.html",
    controller: "HeaderCtrl"
  };
});
