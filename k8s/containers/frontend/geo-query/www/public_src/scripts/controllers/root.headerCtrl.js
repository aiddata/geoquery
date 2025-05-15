angular.module('aiddataDET')
.controller('HeaderCtrl', function($scope, $rootScope, $log, $stateParams, $state, $timeout, $cookies, queryFactory, spinFactory, info) {

  $scope.currentStep = $state;
  $scope.queryLen = 0;
  $scope.highlight = '';

  var tooltipShown = false;

  $scope.activate = function (tab) {
    $scope.sidebarOpen = true;
    $rootScope.$broadcast('sidebar:open', tab);
  };

  $rootScope.$on('query:updated', function() {
    var oldSize = $scope.queryLen,
        newSize = queryFactory.querySize();
    $scope.queryLen = newSize;
    $scope.highlight = oldSize > newSize ? 'context-danger' : 'md-accent';

    if (!tooltipShown) {
      attachPopover();
      tooltipShown = true;
    }

    $timeout(function() {
      $scope.highlight = $scope.queryLen ? 'md-primary' : '';
    }, 1500);
  });

  $scope.pastRequests = function() {
    return $cookies.get('email') ? $state.go('requests', { email: $cookies.get('email') }) :
      $state.go('login');
  };

  $rootScope.$on('$viewContentLoaded', function() {
    $scope.currentStep = $state.current.name;
    $scope.showSteps = $scope.currentStep === 'map' ||
                       $scope.currentStep.indexOf('search') >= 0 ||
                       $scope.currentStep === 'checkout';
  });

  /* Create Popover */
  function attachPopover () {
    var popoverSettings = {
      content: [
        '<p>Add another selection to your request, or if you are finished, click here to submit.</p>',
        '<button class="md-button md-raised md-primary pull-right" flex id="closePopover">Got It</button>'
      ].join('\n'),
      container: 'body',
      html: true,
      placement: 'bottom'
    };

    $('#submitRequestBtn').popover(popoverSettings)
       .on('shown.bs.popover', function() {
         var btn = $(this);
         $('body').click(function () {
           btn.popover('destroy');
         });
       })
       .popover('show');
  }

});
