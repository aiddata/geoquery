angular.module('aiddataDET')
.directive('headerPreviousRequests', function($window) {
  return {
    restrict: "E",
    scope: {
      'menu': '=menuControl'
    },
    link: function(scope, element, attrs) {},
    templateUrl: "views/components/header.previousRequests.html"//,
    // controller: "PreviousRequestsCtrl"
  };
});
