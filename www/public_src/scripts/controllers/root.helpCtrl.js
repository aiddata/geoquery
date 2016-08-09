angular.module('aiddataDET')
.controller('HelpCtrl', function($scope, $rootScope, $log, language) {
  $scope.content = language.help;
});
