angular.module('aiddataDET')
.directive('headerHelp', function($window) {
  return {
    restrict: "E",
    scope: {
      'menu': '=menuControl',
      'option': '=menuOption'
    },
    link: function(scope, element, attrs) {},
    templateUrl: "views/components/header.help.html"//,
    // controller: "HelpCtrl"
  };
});
